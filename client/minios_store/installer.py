"""Recipe installer for MiniOS Store.

Delegates module building to apt2sb and script2sb system utilities.
For system mode, runs apt/script/deb directly on the host.
"""

import asyncio
import functools
import gettext
import logging
import os
import stat
import subprocess
import tempfile
import urllib.request

from . import config

# Internationalization
APP_NAME = "minios-store"
LOCALE_DIR = "/usr/share/locale"
gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext

logger = logging.getLogger("minios_store.installer")


class InstallationError(Exception):
    """Raised when a recipe installation fails."""


class InstallCancelled(Exception):
    """Raised when installation is cancelled by user."""


class Installer:
    """Installs recipes using apt2sb/script2sb or directly on the host."""

    def __init__(self, modules_dir=None, is_fallback_dir=False):
        self._cancelled = False
        self._current_process = None
        self.modules_dir = modules_dir or config.MODULES_DIR
        self.is_fallback_dir = is_fallback_dir
        self.last_module_filename = None

    def cancel(self):
        """Cancel the current installation."""
        self._cancelled = True
        if self._current_process is not None:
            try:
                self._current_process.terminate()
            except ProcessLookupError:
                pass
            logger.info("Installation cancelled by user")  # logger stays English

    def reset(self):
        """Reset cancellation state for a new installation batch."""
        self._cancelled = False
        self._current_process = None
        self.last_module_filename = None

    def _check_cancelled(self):
        """Check if installation was cancelled.

        Raises:
            InstallCancelled: If cancel() was called.
        """
        if self._cancelled:
            raise InstallCancelled("Installation cancelled by user")

    def _run_cmd(self, cmd, cwd=None, env=None, line_callback=None):
        """Run a command on the host system, streaming output line-by-line.

        Args:
            cmd: Command list to execute.
            cwd: Working directory for the command.
            env: Additional environment variables.
            line_callback: Optional callable(line_str) called for each output
                line in real time.  Called from the worker thread.

        Raises:
            InstallationError: If the command fails.
            InstallCancelled: If cancelled during execution.
        """
        self._check_cancelled()

        run_env = dict(os.environ)
        run_env.update(config.APT_ENV)
        if env:
            run_env.update(env)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=cwd,
                env=run_env,
            )
            self._current_process = proc

            collected = []
            for line in (proc.stdout or []):
                text = line.rstrip("\n")
                collected.append(text)
                if line_callback:
                    try:
                        line_callback(text)
                    except Exception:
                        pass

            proc.wait()
            self._current_process = None

            if self._cancelled:
                raise InstallCancelled(_("Installation cancelled by user"))

            if proc.returncode != 0:
                raise InstallationError(
                    _("Command failed (exit %d): %s") % (
                        proc.returncode, " ".join(cmd),
                    ) + "\n" + "\n".join(collected[-30:])
                )

            stdout_text = "\n".join(collected)
            return subprocess.CompletedProcess(
                cmd, proc.returncode, stdout_text, ""
            )

        except InstallCancelled:
            raise
        except InstallationError:
            raise
        except Exception as e:
            self._current_process = None
            raise InstallationError(
                _("Failed to execute %s: %s") % (" ".join(cmd), str(e))
            )

    # ------------------------------------------------------------------
    # Module mode: delegate to apt2sb / script2sb
    # ------------------------------------------------------------------

    def _build_module_filename(self, recipe_id, level, custom_name=""):
        """Build the output module filename.

        Args:
            recipe_id: Recipe identifier.
            level: Module level string (e.g. "05") or "auto".
            custom_name: Optional custom name to use instead of recipe_id.

        Returns:
            Filename string like "05-firefox.sb" or "firefox.sb".
        """
        # Use custom name if provided, otherwise use recipe_id
        name = custom_name if custom_name else recipe_id
        
        if level and level != "auto":
            return "{}-{}.sb".format(level, name)
        return "{}.sb".format(name)

    def _install_module_apt(self, recipe, line_callback=None, custom_name=""):
        """Install packages via apt2sb and produce a .sb module.

        Args:
            recipe: Recipe dict with 'packages', 'level', 'compression'.
            line_callback: Optional callable(line_str) for streaming output.
            custom_name: Optional custom name for the module file.

        Raises:
            InstallationError: If apt2sb fails.
        """
        packages = [str(p) for p in recipe.get("packages", [])]
        if not packages:
            raise InstallationError(
                _("No packages specified for apt method")
            )

        recipe_id = recipe["id"]
        level = recipe.get("level", "")
        compression = recipe.get("compression", config.DEFAULT_COMPRESSION)
        filename = self._build_module_filename(recipe_id, level, custom_name)

        cmd = ["apt2sb", "install", "-y", "--no-install-recommends"]
        cmd += ["-n", filename]
        if level and level != "auto":
            cmd += ["-l", level]
        cmd += ["-c", compression]
        cmd += packages

        logger.info(
            "Running apt2sb for %s: %s", recipe_id, " ".join(cmd)
        )

        os.makedirs(self.modules_dir, exist_ok=True)
        self._run_cmd(cmd, cwd=self.modules_dir,
                      line_callback=line_callback)

        module_path = os.path.join(self.modules_dir, filename)
        if not os.path.exists(module_path):
            raise InstallationError(
                _("Module file not found after apt2sb: %s") % module_path
            )

        size_mb = os.path.getsize(module_path) / (1024 * 1024)
        logger.info("Module built: %s (%.1f MB)", module_path, size_mb)
        return module_path

    def _install_module_script(self, recipe, line_callback=None, custom_name=""):
        """Install via script2sb and produce a .sb module.

        Args:
            recipe: Recipe dict with 'script', 'level', 'compression'.
            line_callback: Optional callable(line_str) for streaming output.
            custom_name: Optional custom name for the module file.

        Raises:
            InstallationError: If script2sb fails.
        """
        script_content = recipe.get("script", "")
        if not script_content:
            raise InstallationError(
                _("No script specified for script method")
            )

        recipe_id = recipe["id"]
        level = recipe.get("level", "")
        compression = recipe.get("compression", config.DEFAULT_COMPRESSION)
        filename = self._build_module_filename(recipe_id, level, custom_name)

        # Write script to a temp file
        fd, script_path = tempfile.mkstemp(
            prefix="minios-store-", suffix=".sh"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(script_content)
            os.chmod(
                script_path,
                stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,
            )

            cmd = ["script2sb", "-s", script_path]
            cmd += ["-n", filename]
            if level and level != "auto":
                cmd += ["-l", level]
            cmd += ["-c", compression]

            logger.info(
                "Running script2sb for %s: %s", recipe_id, " ".join(cmd)
            )

            os.makedirs(self.modules_dir, exist_ok=True)
            self._run_cmd(cmd, cwd=self.modules_dir,
                          line_callback=line_callback)

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        module_path = os.path.join(self.modules_dir, filename)
        if not os.path.exists(module_path):
            raise InstallationError(
                _("Module file not found after script2sb: %s") % module_path
            )

        size_mb = os.path.getsize(module_path) / (1024 * 1024)
        logger.info("Module built: %s (%.1f MB)", module_path, size_mb)
        return module_path

    def _install_module_deb(self, recipe, line_callback=None, custom_name=""):
        """Download a .deb and install it via apt2sb to produce a .sb module.

        apt2sb supports installing local .deb files when passed as ./path.deb.

        Args:
            recipe: Recipe dict with 'debUrl', 'level', 'compression'.
            line_callback: Optional callable(line_str) for streaming output.
            custom_name: Optional custom name for the module file.

        Raises:
            InstallationError: If download or apt2sb fails.
        """
        deb_url = recipe.get("debUrl", "")
        if not deb_url:
            raise InstallationError(
                _("No debUrl specified for deb method")
            )

        recipe_id = recipe["id"]
        level = recipe.get("level", "")
        compression = recipe.get("compression", config.DEFAULT_COMPRESSION)
        filename = self._build_module_filename(recipe_id, level, custom_name)

        # Download the .deb file to a temp location
        deb_basename = (
            os.path.basename(deb_url.split("?")[0]) or "package.deb"
        )
        if not deb_basename.endswith(".deb"):
            deb_basename += ".deb"

        fd, deb_path = tempfile.mkstemp(
            prefix="minios-store-", suffix=".deb"
        )
        os.close(fd)

        try:
            logger.info("Downloading %s", deb_url)
            urllib.request.urlretrieve(deb_url, deb_path)
        except Exception as e:
            try:
                os.unlink(deb_path)
            except OSError:
                pass
            raise InstallationError(
                _("Failed to download %s: %s") % (deb_url, str(e))
            )

        self._check_cancelled()

        try:
            cmd = ["apt2sb", "install", "-y"]
            cmd += ["-n", filename]
            if level and level != "auto":
                cmd += ["-l", level]
            cmd += ["-c", compression]
            cmd += [deb_path]

            logger.info(
                "Running apt2sb (deb) for %s: %s",
                recipe_id, " ".join(cmd),
            )

            os.makedirs(self.modules_dir, exist_ok=True)
            self._run_cmd(cmd, cwd=self.modules_dir,
                          line_callback=line_callback)

        finally:
            try:
                os.unlink(deb_path)
            except OSError:
                pass

        module_path = os.path.join(self.modules_dir, filename)
        if not os.path.exists(module_path):
            raise InstallationError(
                _("Module file not found after apt2sb: %s") % module_path
            )

        size_mb = os.path.getsize(module_path) / (1024 * 1024)
        logger.info("Module built: %s (%.1f MB)", module_path, size_mb)
        return module_path

    # ------------------------------------------------------------------
    # System mode: install directly on the running system
    # ------------------------------------------------------------------

    def _install_system_apt(self, recipe, line_callback=None):
        """Install packages via apt-get directly on host."""
        packages = [str(p) for p in recipe.get("packages", [])]
        if not packages:
            raise InstallationError(
                _("No packages specified for apt method")
            )

        logger.info(
            "Installing %d packages to system: %s",
            len(packages), ", ".join(packages),
        )

        self._check_cancelled()
        self._run_cmd(["apt-get", "update", "-qq"],
                      line_callback=line_callback)
        self._check_cancelled()

        cmd = [
            "apt-get", "install", "-y",
            "--no-install-recommends",
            "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dpkg::Options::=--force-confold",
        ] + packages
        self._run_cmd(cmd, line_callback=line_callback)
        self._run_cmd(["apt-get", "clean"], line_callback=line_callback)

        logger.info(
            "System APT install completed for: %s", recipe.get("name")
        )

    def _install_system_script(self, recipe, line_callback=None):
        """Run install script directly on host."""
        script_content = recipe.get("script", "")
        if not script_content:
            raise InstallationError(
                _("No script specified for script method")
            )

        logger.info(
            "Running install script on system: %s", recipe.get("name")
        )

        fd, script_path = tempfile.mkstemp(
            prefix="minios-store-", suffix=".sh"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(script_content)
            os.chmod(
                script_path,
                stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,
            )
            self._run_cmd(["bash", script_path],
                          line_callback=line_callback)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        logger.info(
            "System script install completed for: %s", recipe.get("name")
        )

    def _install_system_deb(self, recipe, line_callback=None):
        """Download and install .deb directly on host."""
        deb_url = recipe.get("debUrl", "")
        if not deb_url:
            raise InstallationError(
                _("No debUrl specified for deb method")
            )

        logger.info(
            "Installing .deb to system: %s (%s)",
            deb_url, recipe.get("name"),
        )

        deb_basename = (
            os.path.basename(deb_url.split("?")[0]) or "package.deb"
        )
        if not deb_basename.endswith(".deb"):
            deb_basename += ".deb"

        fd, deb_path = tempfile.mkstemp(
            prefix="minios-store-", suffix=".deb"
        )
        os.close(fd)

        try:
            urllib.request.urlretrieve(deb_url, deb_path)
        except Exception as e:
            try:
                os.unlink(deb_path)
            except OSError:
                pass
            raise InstallationError(
                _("Failed to download %s: %s") % (deb_url, str(e))
            )

        self._check_cancelled()

        try:
            # Use apt to install .deb file (automatically handles dependencies)
            self._run_cmd(["apt", "install", "-y", deb_path],
                          line_callback=line_callback)
        finally:
            try:
                os.unlink(deb_path)
            except OSError:
                pass

        logger.info(
            "System deb install completed for: %s", recipe.get("name")
        )

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def _install_module(self, recipe, line_callback=None, custom_name=""):
        """Install a recipe as a module using apt2sb/script2sb.

        Args:
            recipe: Recipe dict.
            line_callback: Optional callable(line_str) for streaming output.
            custom_name: Optional custom name for the module file.

        Returns:
            Path to the created module.

        Raises:
            InstallationError: If installation fails.
        """
        method = recipe["method"]
        if method == "apt":
            return self._install_module_apt(recipe, line_callback, custom_name)
        elif method == "script":
            return self._install_module_script(recipe, line_callback, custom_name)
        elif method == "deb":
            return self._install_module_deb(recipe, line_callback, custom_name)
        else:
            raise InstallationError(
                _("Unknown install method: %s") % method
            )

    def _install_system(self, recipe, line_callback=None):
        """Install a recipe directly on the host.

        Args:
            recipe: Recipe dict.
            line_callback: Optional callable(line_str) for streaming output.

        Raises:
            InstallationError: If installation fails.
        """
        method = recipe["method"]
        if method == "apt":
            self._install_system_apt(recipe, line_callback)
        elif method == "script":
            self._install_system_script(recipe, line_callback)
        elif method == "deb":
            self._install_system_deb(recipe, line_callback)
        else:
            raise InstallationError(
                _("Unknown install method: %s") % method
            )

    # ------------------------------------------------------------------
    # Thread-safe line callback helper
    # ------------------------------------------------------------------

    @staticmethod
    def _make_line_callback(loop, message_callback):
        """Create a thread-safe line callback that sends 'output' messages.

        The returned callable is safe to call from a worker thread.
        It schedules coroutines on the given event loop.

        Args:
            loop: The asyncio event loop (from the main thread).
            message_callback: Async callable(message_dict) or None.

        Returns:
            A sync callable(line_str) or None if message_callback is None.
        """
        if not message_callback:
            return None

        def _on_line(text):
            logger.debug("Output line: %s", text[:100] if len(text) > 100 else text)
            asyncio.run_coroutine_threadsafe(
                message_callback({
                    "type": "output",
                    "text": text,
                }),
                loop,
            )

        return _on_line

    # ------------------------------------------------------------------
    # Single-recipe async wrappers
    # ------------------------------------------------------------------

    async def install_recipe(self, recipe, progress_callback=None,
                             message_callback=None, custom_name=""):
        """Install a single recipe as a module (via apt2sb/script2sb).

        Args:
            recipe: Recipe dict matching InstallRecipe type.
            progress_callback: Async callable(step, detail) for progress.
            message_callback: Async callable(message_dict) for WebSocket msgs.
            custom_name: Optional custom name for the module file.

        Returns:
            Path to the created module.

        Raises:
            InstallationError: If installation fails.
            InstallCancelled: If installation is cancelled.
        """
        recipe_name = recipe.get("name", recipe["id"])

        if progress_callback:
            await progress_callback(
                "install", _("Building module for %s") % recipe_name
            )

        loop = asyncio.get_event_loop()
        line_cb = self._make_line_callback(loop, message_callback)
        module_path = await loop.run_in_executor(
            None, self._install_module, recipe, line_cb, custom_name
        )

        if progress_callback:
            await progress_callback("done", _("Module ready"))

        return module_path

    async def install_recipe_system(self, recipe, progress_callback=None,
                                    message_callback=None):
        """Install a single recipe directly on the host.

        Args:
            recipe: Recipe dict matching InstallRecipe type.
            progress_callback: Async callable(step, detail) for progress.
            message_callback: Async callable(message_dict) for WebSocket msgs.

        Raises:
            InstallationError: If installation fails.
            InstallCancelled: If installation is cancelled.
        """
        recipe_name = recipe.get("name", recipe["id"])

        if progress_callback:
            await progress_callback(
                "install", _("Installing %s") % recipe_name
            )

        loop = asyncio.get_event_loop()
        line_cb = self._make_line_callback(loop, message_callback)
        await loop.run_in_executor(
            None, self._install_system, recipe, line_cb
        )

        if progress_callback:
            await progress_callback("done", _("Installed to system"))

    # ------------------------------------------------------------------
    # Batch: single combined module via script2sb
    # ------------------------------------------------------------------

    def _build_combined_script(self, recipes):
        """Build a combined install script for multiple recipes.

        Generates a bash script that performs all installations
        sequentially: apt-get installs, script executions, deb downloads.

        Args:
            recipes: List of recipe dicts.

        Returns:
            Script content as string.
        """
        lines = ["#!/bin/bash", "set -e", "export LANG=C", ""]

        for recipe in recipes:
            method = recipe["method"]
            name = recipe.get("name", recipe["id"])
            lines.append("# --- {} ({}) ---".format(name, method))

            if method == "apt":
                # Ensure all package names are strings
                packages = [str(p) for p in recipe.get("packages", [])]
                if packages:
                    lines.append("apt-get update -qq")
                    lines.append(
                        "apt-get install -y --no-install-recommends "
                        + " ".join(packages)
                    )
                    lines.append("apt-get clean")

            elif method == "script":
                script_content = recipe.get("script", "")
                if script_content:
                    # Embed script inline
                    lines.append(script_content)

            elif method == "deb":
                deb_url = recipe.get("debUrl", "")
                if deb_url:
                    deb_basename = (
                        os.path.basename(deb_url.split("?")[0])
                        or "package.deb"
                    )
                    if not deb_basename.endswith(".deb"):
                        deb_basename += ".deb"
                    deb_tmp = "/tmp/{}".format(deb_basename)
                    lines.append(
                        'wget -O "{}" "{}"'.format(deb_tmp, deb_url)
                    )
                    lines.append(
                        'apt install -y "{}"'.format(deb_tmp)
                    )
                    lines.append('rm -f "{}"'.format(deb_tmp))

            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Batch installation orchestrator
    # ------------------------------------------------------------------

    async def install_batch(self, recipes, message_callback=None,
                            mode="module", packaging="single", module_name=""):
        """Install a batch of recipes.

        Dispatches to one of three installation paths:
        - mode=system: install each recipe directly on host
        - mode=module, packaging=separate: each recipe gets its own module
        - mode=module, packaging=single: all recipes combined into one module

        Args:
            recipes: List of recipe dicts.
            message_callback: Async callable(message_dict) for WebSocket msgs.
            mode: "module" (build .sb files) or "system" (direct install).
            packaging: "single" (one combined module) or "separate" (per-recipe).
            module_name: Custom name for module(s). Used as-is for single,
                         or as prefix for separate packaging.

        Returns:
            Tuple of (successful_ids, failed_ids).
        """
        self.reset()
        total = len(recipes)
        successful = []
        failed = []

        if message_callback:
            await message_callback({
                "type": "install_start",
                "total": total,
            })

        if mode == "system":
            await self._batch_system(
                recipes, successful, failed, message_callback,
            )
        elif mode == "module" and packaging == "single":
            await self._batch_module_single(
                recipes, successful, failed, message_callback, module_name,
            )
        else:
            # mode=module, packaging=separate (default/fallback)
            await self._batch_module_separate(
                recipes, successful, failed, message_callback, module_name,
            )

        if message_callback:
            await message_callback({
                "type": "install_complete",
                "successful": successful,
                "failed": failed,
            })
            
            # Send module location info if modules were installed successfully
            if mode == "module" and successful:
                # Determine module name to display
                if packaging == "single" and self.last_module_filename:
                    # Single combined module - show the actual filename
                    display_name = self.last_module_filename
                elif len(successful) == 1:
                    # One module installed - show recipe name
                    display_name = recipes[0]["name"]
                else:
                    # Multiple separate modules - show count
                    display_name = _("%d modules") % len(successful)
                
                logger.info(
                    "Module location notification: display_name='%s', "
                    "last_module_filename='%s', packaging='%s'",
                    display_name, self.last_module_filename, packaging
                )
                
                await message_callback({
                    "type": "module_location",
                    "directory": self.modules_dir,
                    "isFallback": self.is_fallback_dir,
                    "moduleName": display_name,
                })

        return successful, failed

    async def _batch_system(self, recipes, successful, failed,
                            message_callback):
        """Install recipes directly to the running system."""
        total = len(recipes)

        for i, recipe in enumerate(recipes):
            recipe_id = recipe["id"]
            recipe_name = recipe.get("name", recipe_id)

            if self._cancelled:
                failed.extend(r["id"] for r in recipes[i:])
                break

            async def progress_cb(step, detail,
                                  _id=recipe_id, _name=recipe_name, _i=i):
                if message_callback:
                    await message_callback({
                        "type": "install_progress",
                        "recipeId": _id,
                        "recipeName": _name,
                        "step": step,
                        "progress": _i + 1,
                        "total": total,
                        "current": _i + 1,
                    })
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("[{}/{}] {} - {}").format(
                            _i + 1, total, _name, detail
                        ),
                    })

            try:
                await self.install_recipe_system(
                    recipe, progress_cb, message_callback
                )
                successful.append(recipe_id)

                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("Installed to system: %s") % (
                            recipe_name
                        ),
                    })

            except InstallCancelled:
                failed.append(recipe_id)
                failed.extend(r["id"] for r in recipes[i + 1:])
                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "warn",
                        "message": _("Installation cancelled"),
                    })
                break

            except InstallationError as e:
                failed.append(recipe_id)
                logger.error(
                    "Failed to install %s: %s", recipe_name, str(e)
                )
                if message_callback:
                    await message_callback({
                        "type": "install_error",
                        "recipeId": recipe_id,
                        "error": str(e),
                    })
                    await message_callback({
                        "type": "log",
                        "level": "error",
                        "message": _("Failed to install %s: %s") % (
                            recipe_name, str(e)
                        ),
                    })

    async def _batch_module_separate(self, recipes, successful, failed,
                                     message_callback, module_name=""):
        """Install recipes as separate modules (one per recipe).
        
        Args:
            recipes: List of recipe dicts.
            successful: List to append successful recipe IDs to.
            failed: List to append failed recipe IDs to.
            message_callback: Async callable for progress updates.
            module_name: Custom name prefix (optional). Used as prefix for each module.
        """
        total = len(recipes)

        for i, recipe in enumerate(recipes):
            recipe_id = recipe["id"]
            recipe_name = recipe.get("name", recipe_id)
            
            # For separate packaging, use module_name as prefix if provided
            custom_name = ""
            if module_name:
                custom_name = "{}-{}".format(module_name, recipe_id)

            if self._cancelled:
                failed.extend(r["id"] for r in recipes[i:])
                break

            async def progress_cb(step, detail,
                                  _id=recipe_id, _name=recipe_name, _i=i):
                if message_callback:
                    await message_callback({
                        "type": "install_progress",
                        "recipeId": _id,
                        "recipeName": _name,
                        "step": step,
                        "progress": _i + 1,
                        "total": total,
                        "current": _i + 1,
                    })
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("[{}/{}] {} - {}").format(
                            _i + 1, total, _name, detail
                        ),
                    })

            try:
                await self.install_recipe(
                    recipe, progress_cb, message_callback, custom_name
                )
                successful.append(recipe_id)

                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("Module built: %s") % recipe_name,
                    })

            except InstallCancelled:
                failed.append(recipe_id)
                failed.extend(r["id"] for r in recipes[i + 1:])
                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "warn",
                        "message": _("Installation cancelled"),
                    })
                break

            except InstallationError as e:
                failed.append(recipe_id)
                logger.error(
                    "Failed to install %s: %s", recipe_name, str(e)
                )
                if message_callback:
                    await message_callback({
                        "type": "install_error",
                        "recipeId": recipe_id,
                        "error": str(e),
                    })
                    await message_callback({
                        "type": "log",
                        "level": "error",
                        "message": _("Failed to install %s: %s") % (
                            recipe_name, str(e)
                        ),
                    })

    async def _batch_module_single(self, recipes, successful, failed,
                                   message_callback, module_name=""):
        """Install all recipes into one combined module via script2sb.
        
        Args:
            recipes: List of recipe dicts.
            successful: List to append successful recipe IDs to.
            failed: List to append failed recipe IDs to.
            message_callback: Async callable for progress updates.
            module_name: Custom module name (optional). If empty, uses recipe IDs.
        """
        total = len(recipes)
        all_recipe_ids = [r["id"] for r in recipes]
        
        # Use custom name if provided, otherwise combine recipe IDs
        if module_name:
            combined_name = module_name
        else:
            combined_name = "+".join(all_recipe_ids)

        # Display name: use recipe name when single, "Combined module" for multiple
        if total == 1:
            display_name = recipes[0].get("name", combined_name)
        else:
            display_name = _("Combined module")
            
        compression = config.DEFAULT_COMPRESSION

        if message_callback:
            await message_callback({
                "type": "log",
                "level": "info",
                "message": _("Building single module for %d recipe(s)") % (
                    total
                ),
            })
            await message_callback({
                "type": "install_progress",
                "recipeId": combined_name,
                "recipeName": display_name,
                "step": "install",
                "progress": 0,
                "total": 1,
                "current": 0,
            })

        # Check if all recipes are apt-only (can use apt2sb directly)
        all_apt = all(r["method"] == "apt" for r in recipes)

        if all_apt:
            # Combine all packages into a single apt2sb call
            all_packages = []
            for recipe in recipes:
                # Ensure all package names are strings
                packages = recipe.get("packages", [])
                all_packages.extend(str(p) for p in packages)

            if not all_packages:
                failed.extend(all_recipe_ids)
                if message_callback:
                    await message_callback({
                        "type": "install_error",
                        "recipeId": combined_name,
                        "error": _("No packages specified"),
                    })
                return

            filename = "{}.sb".format(combined_name)
            self.last_module_filename = filename
            cmd = ["apt2sb", "install", "-y", "--no-install-recommends"]
            cmd += ["-n", filename]
            cmd += ["-c", compression]
            cmd += all_packages

            logger.info(
                "Running apt2sb (combined) for %s: %s",
                combined_name, " ".join(cmd),
            )

            try:
                loop = asyncio.get_event_loop()
                line_cb = self._make_line_callback(loop, message_callback)
                os.makedirs(self.modules_dir, exist_ok=True)
                
                # Update progress to show we're working
                if message_callback:
                    await message_callback({
                        "type": "install_progress",
                        "recipeId": combined_name,
                        "recipeName": display_name,
                        "step": "install",
                        "progress": 1,
                        "total": total,
                        "current": 1,
                    })
                
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        self._run_cmd, cmd,
                        cwd=self.modules_dir,
                        line_callback=line_cb,
                    ),
                )
                successful.extend(all_recipe_ids)

                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("Module built: %s") % filename,
                    })

            except InstallCancelled:
                failed.extend(all_recipe_ids)
                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "warn",
                        "message": _("Installation cancelled"),
                    })

            except InstallationError as e:
                failed.extend(all_recipe_ids)
                logger.error(
                    "Failed to build combined module: %s", str(e)
                )
                if message_callback:
                    await message_callback({
                        "type": "install_error",
                        "recipeId": combined_name,
                        "error": str(e),
                    })
        else:
            # Mixed methods: build a combined script and use script2sb
            script_content = self._build_combined_script(recipes)
            filename = "{}.sb".format(combined_name)
            self.last_module_filename = filename

            fd, script_path = tempfile.mkstemp(
                prefix="minios-store-combined-", suffix=".sh"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(script_content)
                os.chmod(
                    script_path,
                    stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,
                )

                cmd = ["script2sb", "-s", script_path]
                cmd += ["-n", filename]
                cmd += ["-c", compression]

                logger.info(
                    "Running script2sb (combined) for %s: %s",
                    combined_name, " ".join(cmd),
                )

                loop = asyncio.get_event_loop()
                line_cb = self._make_line_callback(loop, message_callback)
                os.makedirs(self.modules_dir, exist_ok=True)
                
                # Update progress to show we're working
                if message_callback:
                    await message_callback({
                        "type": "install_progress",
                        "recipeId": combined_name,
                        "recipeName": display_name,
                        "step": "install",
                        "progress": 1,
                        "total": total,
                        "current": 1,
                    })
                
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        self._run_cmd, cmd,
                        cwd=self.modules_dir,
                        line_callback=line_cb,
                    ),
                )
                successful.extend(all_recipe_ids)

                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "info",
                        "message": _("Module built: %s") % filename,
                    })

            except InstallCancelled:
                failed.extend(all_recipe_ids)
                if message_callback:
                    await message_callback({
                        "type": "log",
                        "level": "warn",
                        "message": _("Installation cancelled"),
                    })

            except InstallationError as e:
                failed.extend(all_recipe_ids)
                logger.error(
                    "Failed to build combined module: %s", str(e)
                )
                if message_callback:
                    await message_callback({
                        "type": "install_error",
                        "recipeId": combined_name,
                        "error": str(e),
                    })

            finally:
                try:
                    os.unlink(script_path)
                except OSError:
                    pass
