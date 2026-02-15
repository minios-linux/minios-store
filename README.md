# MiniOS Store

A web-based application store for [MiniOS](https://minios.dev) Linux distribution. Browse, search, and install application recipes as squashfs modules.

**Live**: [store.minios.dev](https://store.minios.dev)

## Components

- **Web UI** (`web/`) -- React 19 + TypeScript + Vite + Tailwind CSS single-page application with admin panel
- **Python Daemon** (`client/`) -- asyncio WebSocket server that handles recipe installation on the local machine
- **GTK3 GUI** (`client/minios_store/gui.py`) -- standalone installer for `minios-store://` URIs (works without WebSocket daemon)
- **Recipes** (`recipes/`) -- YAML recipe definitions organized by category
- **Build Tools** (`tools/`) -- `repo_parser.py` (DEP-11 AppStream -> YAML), `build_recipes.py` (YAML -> JSON + media download)

## Quick Start

### Web UI Development

```bash
cd web
npm install
npm run dev
```

The development server starts at `http://localhost:5174`.

### Python Daemon

The daemon listens on `ws://127.0.0.1:8765` and handles installation requests from the web UI. Requires root privileges for apt/dpkg/mount operations.

```bash
# Run directly
sudo python3 -m client.minios_store.server

# Or via launcher
sudo bin/minios-store-daemon

# With verbose logging
sudo python3 -m client.minios_store.server --verbose
```

### GTK3 GUI Installer

Standalone graphical installer for `minios-store://` URIs. Works without the WebSocket daemon.

```bash
# Via launcher
minios-store-install "minios-store://install?mode=module&recipes=vlc:auto:zstd&packaging=single"

# Or with command-line arguments
minios-store-install --mode module --packaging single --recipes vlc:auto:zstd
```

### Building Recipes

```bash
# Parse DEP-11 metadata from Debian repos into YAML recipes
python3 tools/repo_parser.py --dist trixie

# Build JSON + download screenshots/icons from YAML recipes
python3 tools/build_recipes.py

# Validate recipes only (no download)
python3 tools/build_recipes.py --validate

# Build JSON without downloading media (fast)
python3 tools/build_recipes.py --no-screenshots --no-icons
```

### Building Web UI for Production

```bash
cd web
npm run build
```

Output goes to `web/dist/`.

## Installation

### From Debian Package

```bash
sudo apt install ./minios-store_*.deb
```

### From Source

Build the Debian package:

```bash
# Build the package
debuild -uc -us

# Install it
sudo apt install ../minios-store_*.deb
```

## Architecture

The store consists of two independently deployable parts:

1. **Web frontend** -- static SPA hosted at [store.minios.dev](https://store.minios.dev) via GitHub Pages. Loads recipe data from static JSON files (recipes-index.json for browsing, individual recipe JSON files for detail views). No server required for browsing.
2. **WebSocket daemon** -- runs locally on MiniOS machines as a systemd service (`minios-store`). Receives install commands from the frontend over `ws://127.0.0.1:8765` and builds squashfs modules.

### Data Pipeline

```
Debian DEP-11 AppStream metadata
        |
        v
  repo_parser.py --dist trixie     --> recipes/*.yml (YAML files)
        |
        v
  build_recipes.py                  --> web/public/data/recipes.json
                                        web/public/data/recipes-index.json
                                        web/public/data/recipes/{id}.json
                                        web/public/screenshots/{id}/
                                        web/public/icons/{id}.png
```

### Installation Flow

1. User browses recipes in the web UI and adds them to the cart
2. User clicks "Install" -- the UI sends recipes over WebSocket to the daemon
3. The daemon installs packages (apt/script/deb) into a temporary overlay
4. Changes are packed into a squashfs module at the specified compression and level
5. The module is placed in the MiniOS modules directory

### WebSocket Protocol

Messages are JSON with a `type` discriminant field. See `web/src/lib/types.ts` for complete schemas.

- **Client -> Server**: `install`, `cancel`, `ping`
- **Server -> Client**: `system_info`, `install_start`, `install_progress`, `install_complete`, `install_error`, `log`, `pong`

## Recipe Categories

| Category | Directory |
|---|---|
| Development | `recipes/development/` |
| Games | `recipes/games/` |
| Graphics | `recipes/graphics/` |
| Internet | `recipes/internet/` |
| Multimedia | `recipes/multimedia/` |
| Office | `recipes/office/` |
| Security | `recipes/security/` |
| System | `recipes/system/` |

## Internationalization

The store supports 8 languages: English (en), Russian (ru), German (de), Spanish (es), French (fr), Italian (it), Portuguese Brazilian (pt-BR), Indonesian (id). Translations are managed via the admin panel (accessible on localhost) with AI-assisted translation support.

- **UI strings**: `web/public/translations/{lang}.json`
- **Recipe translations**: `web/public/data/recipe-translations/{lang}/{recipe-id}.json`
- **Python GUI strings**: `po/{lang}.po` (compiled to `.mo` files during package build)

## Admin Panel

Accessible via the Settings icon when running on `localhost`. Features:

- Recipe CRUD editor
- Category manager with drag-and-drop ordering
- UI string translation editor
- Recipe translation editor
- AI-assisted batch translation (OpenAI, Gemini, Groq, local OpenCode)

## Deployment

### GitHub Pages (store.minios.dev)

The frontend is deployed to GitHub Pages with a custom domain. The `CNAME` file in `web/public/` configures the `store.minios.dev` domain.

### Local (MiniOS machines)

Install the Debian package:

```bash
sudo apt install ./minios-store_*.deb
sudo systemctl enable --now minios-store
```

## License

GPL-2+
