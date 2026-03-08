"""WebSocket server for MiniOS Store daemon.

Listens for installation requests via WebSocket and dispatches
them to the installer. Handles ping/pong and cancel messages.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys

import websockets

from . import __version__, config
from .installer import Installer
from .logger import setup_logging

logger = logging.getLogger("minios_store.server")


class StoreServer:
    """WebSocket server handling store installation requests."""

    def __init__(self):
        # Determine writable modules directory
        modules_dir, is_fallback = config.get_writable_modules_dir()
        self.installer = Installer(modules_dir=modules_dir, is_fallback_dir=is_fallback)
        self._installing = False
        self._clients = set()
        self._system_info = config.get_system_info()
        
        # Installation state tracking
        self._install_state = {
            "active": False,
            "current": 0,
            "total": 0,
            "recipe_name": "",
            "step": "",
            "successful": [],
            "failed": [],
            "output_lines": [],
        }
        
        logger.info(
            "System info: %s %s (%s) arch=%s",
            self._system_info.get("id"),
            self._system_info.get("version_id"),
            self._system_info.get("codename"),
            self._system_info.get("arch"),
        )
        
        # Log modules directory
        if is_fallback:
            logger.warning(
                "Using fallback modules directory: %s (primary location not writable)",
                modules_dir
            )
        else:
            logger.info("Using modules directory: %s", modules_dir)

    async def handle_message(self, websocket, raw_message):
        """Process a single WebSocket message.

        Args:
            websocket: The WebSocket connection.
            raw_message: Raw message string from client.
        """
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            await self._send(websocket, {
                "type": "install_error",
                "error": "Invalid JSON message",
            })
            return

        msg_type = message.get("type")
        logger.debug("Received message type: %s", msg_type)

        if msg_type == "ping":
            await self._send(websocket, {"type": "pong"})

        elif msg_type == "get_status":
            await self._handle_get_status(websocket)

        elif msg_type == "install":
            await self._handle_install(websocket, message)

        elif msg_type == "cancel":
            await self._handle_cancel(websocket)

        elif msg_type == "open_folder":
            await self._handle_open_folder(websocket, message)

        else:
            logger.warning("Unknown message type: %s", msg_type)
            await self._send(websocket, {
                "type": "install_error",
                "error": "Unknown message type: {}".format(msg_type),
            })

    async def _handle_install(self, websocket, message):
        """Handle an install request.

        Args:
            websocket: The WebSocket connection.
            message: Parsed install message dict.
        """
        if self._installing:
            await self._send(websocket, {
                "type": "install_error",
                "error": "Another installation is already in progress",
            })
            return

        recipes = message.get("recipes", [])
        if not recipes:
            await self._send(websocket, {
                "type": "install_error",
                "error": "No recipes provided",
            })
            return

        mode = message.get("mode", "module")
        packaging = message.get("packaging", "single")
        module_name = message.get("moduleName", "").strip()

        if mode not in ("module", "system"):
            await self._send(websocket, {
                "type": "install_error",
                "error": "Invalid mode '{}'".format(mode),
            })
            return

        if packaging not in ("single", "separate"):
            await self._send(websocket, {
                "type": "install_error",
                "error": "Invalid packaging '{}'".format(packaging),
            })
            return

        # Validate recipes
        for recipe in recipes:
            if not recipe.get("id"):
                await self._send(websocket, {
                    "type": "install_error",
                    "error": "Recipe missing 'id' field",
                })
                return
            if recipe.get("method") not in ("apt", "script", "deb"):
                await self._send(websocket, {
                    "type": "install_error",
                    "error": "Invalid method '{}' for recipe '{}'".format(
                        recipe.get("method"), recipe.get("id")
                    ),
                })
                return

        self._installing = True
        
        # Initialize install state
        self._install_state = {
            "active": True,
            "current": 0,
            "total": len(recipes),
            "recipe_name": "",
            "step": "",
            "successful": [],
            "failed": [],
            "output_lines": [],
        }

        logger.info(
            "Starting installation of %d recipe(s) (mode=%s, packaging=%s%s): %s",
            len(recipes), mode, packaging,
            ", module_name={}".format(module_name) if module_name else "",
            ", ".join(r.get("name", r["id"]) for r in recipes),
        )

        async def send_message(msg):
            # Update state tracking
            if msg.get("type") == "install_start":
                self._install_state["total"] = msg.get("total", len(recipes))
            elif msg.get("type") == "install_progress":
                self._install_state["current"] = msg.get("current", 0)
                self._install_state["recipe_name"] = msg.get("recipeName", "")
                self._install_state["step"] = msg.get("step", "")
            elif msg.get("type") == "output":
                self._install_state["output_lines"].append(msg.get("text", ""))
                # Keep last 500 lines
                if len(self._install_state["output_lines"]) > 500:
                    self._install_state["output_lines"] = self._install_state["output_lines"][-500:]
            elif msg.get("type") == "install_complete":
                self._install_state["successful"] = msg.get("successful", [])
                self._install_state["failed"] = msg.get("failed", [])
                self._install_state["active"] = False
            
            await self._broadcast(msg)

        try:
            successful, failed = await self.installer.install_batch(
                recipes, send_message, mode=mode, packaging=packaging, module_name=module_name,
            )
            logger.info(
                "Installation batch complete: %d successful, %d failed",
                len(successful), len(failed),
            )
        except Exception as e:
            logger.error("Unexpected error during installation: %s", e)
            await self._send(websocket, {
                "type": "install_error",
                "error": "Unexpected error: {}".format(str(e)),
            })
            self._install_state["active"] = False
        finally:
            self._installing = False

    async def _handle_cancel(self, websocket):
        """Handle a cancel request.

        Args:
            websocket: The WebSocket connection.
        """
        if self._installing:
            logger.info("Cancel requested by client")
            self.installer.cancel()
            await self._send(websocket, {
                "type": "log",
                "level": "warn",
                "message": "Cancelling installation...",
            })
        else:
            await self._send(websocket, {
                "type": "log",
                "level": "info",
                "message": "No installation in progress to cancel",
            })

    async def _handle_get_status(self, websocket):
        """Handle a status request.

        Args:
            websocket: The WebSocket connection.
        """
        response = {
            "type": "install_status",
            "installing": self._installing,
        }
        
        # Add detailed state if installation is active
        if self._installing and self._install_state["active"]:
            response.update({
                "current": self._install_state["current"],
                "total": self._install_state["total"],
                "recipeName": self._install_state["recipe_name"],
                "step": self._install_state["step"],
                "successful": self._install_state["successful"],
                "failed": self._install_state["failed"],
                "outputLines": self._install_state["output_lines"][-100:],  # Last 100 lines
            })
        
        await self._send(websocket, response)

    async def _handle_open_folder(self, websocket, message):
        """Handle a request to open a folder in the file manager.

        Args:
            websocket: The WebSocket connection.
            message: The message containing the folder path.
        """
        import subprocess
        import os
        import shutil
        
        path = message.get("path")
        if not path:
            logger.warning("open_folder request missing path")
            return
        
        if not os.path.exists(path):
            logger.warning("open_folder: path does not exist: %s", path)
            await self._send(websocket, {
                "type": "log",
                "level": "error",
                "message": "Folder does not exist: {}".format(path),
            })
            return
        
        logger.info("Opening folder: %s", path)
        
        # Get user and display from message (sent by browser) or use defaults
        user = message.get("user", "live")
        display = message.get("display", ":0")
        
        # Find active X sessions for the user
        try:
            result = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=5
            )
            # Find Xorg process for the user to get the actual DISPLAY
            for line in result.stdout.split('\n'):
                if user in line and 'Xorg' in line:
                    # Extract display from Xorg command line (e.g., "Xorg :10")
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part.startswith(':') and part[1:].split('.')[0].isdigit():
                            display = part.split()[0]
                            logger.info("Found DISPLAY=%s for user %s", display, user)
                            break
                    break
        except Exception as e:
            logger.warning("Could not detect DISPLAY, using default %s: %s", display, e)
        
        logger.info("Opening folder as user %s with DISPLAY=%s", user, display)
        
        # Try different file managers in order of preference
        file_managers = ['xdg-open', 'thunar', 'pcmanfm', 'nautilus', 'dolphin', 'nemo', 'caja']
        opened = False
        
        for fm in file_managers:
            # Check if file manager exists
            if shutil.which(fm) is None:
                continue
            
            try:
                # Use su -c to run command as user with their environment
                cmd = 'DISPLAY={} {} "{}"'.format(display, fm, path)
                subprocess.Popen(
                    ['su', '-', user, '-c', cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                logger.info("Successfully launched %s for folder: %s", fm, path)
                opened = True
                break
            except Exception as e:
                logger.warning("Failed to open with %s: %s", fm, e)
                continue
        
        if not opened:
            logger.error("Failed to open folder: no working file manager found")
            await self._send(websocket, {
                "type": "log",
                "level": "error",
                "message": "Failed to open folder: no working file manager found"
            })



    async def _send(self, websocket, message):
        """Send a JSON message to a WebSocket client.

        Args:
            websocket: The WebSocket connection.
            message: Dict to serialize and send.
        """
        try:
            await websocket.send(json.dumps(message))
        except websockets.exceptions.ConnectionClosed:
            logger.debug("Client disconnected while sending message")

    async def _broadcast(self, message):
        """Send a JSON message to all connected WebSocket clients.

        Args:
            message: Dict to serialize and send.
        """
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                dead.add(ws)
        self._clients -= dead

    async def handler(self, websocket, path=None):
        """WebSocket connection handler.

        Args:
            websocket: The incoming WebSocket connection.
            path: Request path (passed by old websockets 3.x–4.x, unused).
        """
        self._clients.add(websocket)
        remote = websocket.remote_address
        logger.info("Client connected: %s:%s", remote[0], remote[1])

        # Send system info to newly connected client
        await self._send(websocket, {
            "type": "system_info",
            "codename": self._system_info.get("codename"),
            "id": self._system_info.get("id"),
            "name": self._system_info.get("name"),
            "version_id": self._system_info.get("version_id"),
            "arch": self._system_info.get("arch"),
        })

        try:
            # Use recv() loop instead of ``async for message in websocket``
            # because old websockets 3.x–4.x lacks __aiter__ support.
            while True:
                message = await websocket.recv()
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(
                "Client disconnected: %s:%s (code=%s)",
                remote[0], remote[1], e.code,
            )
        except Exception as e:
            logger.error(
                "Error handling client %s:%s: %s",
                remote[0], remote[1], e,
            )
        finally:
            self._clients.discard(websocket)

    async def run(self, host=None, port=None):
        """Start the WebSocket server.

        Args:
            host: Bind address (default from config).
            port: Bind port (default from config).
        """
        host = host or config.WS_HOST
        port = port or config.WS_PORT

        logger.info(
            "MiniOS Store daemon v%s starting on ws://%s:%d",
            __version__, host, port,
        )

        # Setup signal handlers for clean shutdown
        loop = asyncio.get_event_loop()
        stop = loop.create_future()

        def _signal_handler():
            if not stop.done():
                stop.set_result(None)

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

        # Keepalive arguments are supported by newer websockets versions, but
        # can still fail at runtime on older stacks (e.g. websockets 3.x with
        # Python 3.6 on Ubuntu 18.04) when forwarded to loop.create_server().
        # Try with keepalive first, then fall back to a minimal call.
        serve_kwargs = {
            "ping_interval": config.PING_INTERVAL,
            "ping_timeout": config.PING_TIMEOUT,
        }
        try:
            server = await websockets.serve(
                self.handler,
                host,
                port,
                **serve_kwargs
            )
        except TypeError as exc:
            if "ping_interval" not in str(exc):
                raise
            logger.warning(
                "websockets stack does not support ping args; "
                "starting without keepalive options"
            )
            server = await websockets.serve(
                self.handler,
                host,
                port,
            )
        logger.info("Server ready, waiting for connections...")

        try:
            await stop
        finally:
            server.close()
            await server.wait_closed()

        logger.info("Server shutting down")


def main():
    """Entry point for the WebSocket server daemon."""
    parser = argparse.ArgumentParser(
        description="MiniOS Store WebSocket daemon"
    )
    parser.add_argument(
        "--host",
        default=config.WS_HOST,
        help="Bind address (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.WS_PORT,
        help="Bind port (default: %(default)s)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="minios-store {}".format(__version__),
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    # Check for root privileges (needed for apt2sb/script2sb utilities)
    import os
    if os.geteuid() != 0:
        logger.warning(
            "Running without root privileges. "
            "Installation operations will fail."
        )

    server = StoreServer()

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(server.run(host=args.host, port=args.port))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
