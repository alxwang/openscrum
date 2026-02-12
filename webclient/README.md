# OpenScrum Web Client

A modern Vue 3 web client for the OpenScrum agent server, built with PrimeVue, Tailwind CSS, and Lucide icons.

## Features

- 🎨 Clean, Anthropic-inspired UI design
- 💬 Real-time streaming chat interface
- 🔄 Server-Sent Events (SSE) for live updates
- 📝 Markdown rendering with syntax highlighting
- 🎯 Plan/Edit mode switching
- 🔐 Permission request handling
- 📱 Responsive design

## Tech Stack

- **Vue 3** (Composition API)
- **PrimeVue** - UI component library
- **Tailwind CSS** - Utility-first CSS framework
- **Lucide Vue Next** - Icon library
- **Vite** - Build tool
- **Axios** - HTTP client
- **Marked** - Markdown parser
- **Highlight.js** - Code syntax highlighting

## Prerequisites

- Node.js 18+ and npm
- OpenScrum backend server running on `http://localhost:8000`

## Setup

### Quick Setup

Run the setup script:
```bash
./setup.sh
```

### Manual Setup

1. Install dependencies:
```bash
npm install
```

2. Copy environment variables:
```bash
cp .env.example .env
```

3. Start the development server:
```bash
npm run dev
```

The web client will be available at `http://localhost:3000`

## Configuration

Create a `.env` file in the `webclient` directory:

```env
VITE_API_URL=http://localhost:8000
```

## Build

Build for production:
```bash
npm run build
```

Preview production build:
```bash
npm run preview
```

## Project Structure

```
webclient/
├── src/
│   ├── composables/
│   │   └── useApiClient.js    # API client composable
│   ├── components/             # Vue components (to be added)
│   ├── App.vue                 # Main app component
│   ├── main.js                 # App entry point
│   └── style.css               # Global styles
├── index.html                  # HTML template
├── vite.config.js              # Vite configuration
├── tailwind.config.js          # Tailwind configuration
└── package.json                # Dependencies
```

## Development

The app runs on `http://localhost:3000` by default. The Vite dev server proxies API requests to `/api/*` to the backend at `http://localhost:8000`.

## Next Steps

UI design instructions will be provided next to customize the interface further.
