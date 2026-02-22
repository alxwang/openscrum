<template>
  <div class="console-viewer flex flex-col h-full bg-black w-full overflow-hidden">
    <!-- Header -->
    <div class="flex-shrink-0 px-4 py-2 bg-surface-dark border-b border-gray-800 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <span class="text-xs font-mono font-semibold text-gray-300">Terminal Output</span>
      </div>
      <button @click="clearConsole" class="text-xs text-text-muted hover:text-text-inverse transition-colors">Clear</button>
    </div>
    
    <!-- XTERM Container -->
    <div class="flex-1 overflow-hidden relative p-2" ref="terminalContainer"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'
import 'xterm/css/xterm.css'

const props = defineProps({
  output: {
    type: String,
    default: ''
  }
})

const terminalContainer = ref(null)
let term = null
let fitAddon = null

const initTerminal = () => {
  if (!terminalContainer.value) return

  term = new Terminal({
    theme: {
      background: '#000000',
      foreground: '#d4d4d4',
      cursor: '#ffffff',
      cursorAccent: '#000000',
      selection: '#264f78',
      black: '#000000',
      red: '#cd3131',
      green: '#0dbc79',
      yellow: '#e5e510',
      blue: '#2472c8',
      magenta: '#bc3fbc',
      cyan: '#11a8cd',
      white: '#e5e5e5',
      brightBlack: '#666666',
      brightRed: '#f14c4c',
      brightGreen: '#23d18b',
      brightYellow: '#f5f543',
      brightBlue: '#3b8eea',
      brightMagenta: '#d670d6',
      brightCyan: '#29b8db',
      brightWhite: '#e5e5e5'
    },
    fontFamily: '"JetBrains Mono", "Fira Code", monospace',
    fontSize: 12,
    cursorBlink: true,
    disableStdin: true,
    convertEol: true
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)

  term.open(terminalContainer.value)
  fitAddon.fit()

  // Print initial output if any
  if (props.output) {
    term.write(props.output)
  } else {
    term.writeln('\x1b[38;5;8mmaking environment ready...\x1b[0m')
  }

  // Handle window resize
  window.addEventListener('resize', handleResize)
  
  // Create an observer to watch for container size changes (e.g. split pane dragging)
  const resizeObserver = new ResizeObserver(() => {
    handleResize()
  })
  resizeObserver.observe(terminalContainer.value)

  // Store observer for cleanup if needed
  terminalContainer.value.__resizeObserver = resizeObserver
}

const handleResize = () => {
  if (fitAddon) {
    // Add a tiny delay to let DOM settle during split pane dragging
    setTimeout(() => {
      try {
        fitAddon.fit()
      } catch (e) {
        // Ignore fit errors if terminal is hidden
      }
    }, 10)
  }
}

const clearConsole = () => {
  if (term) {
    term.clear()
  }
}

watch(() => props.output, (newOutput) => {
  if (term && newOutput) {
    // Basic diffing to only write new content if it's appending
    // In a real implementation we'd probably use a stream, but this works for props
    term.clear()
    term.write(newOutput)
  }
})

onMounted(() => {
  initTerminal()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (terminalContainer.value && terminalContainer.value.__resizeObserver) {
    terminalContainer.value.__resizeObserver.disconnect()
  }
  if (term) {
    term.dispose()
  }
})

// Expose methods for parent
defineExpose({
  write: (text) => term?.write(text),
  writeln: (text) => term?.writeln(text),
  clear: clearConsole
})
</script>

<style scoped>
/* Ensure terminal takes full height and hides overflow at container level */
.console-viewer :deep(.xterm-viewport) {
  overflow-y: auto !important;
}

/* Custom scrollbar for xterm */
.console-viewer :deep(.xterm-viewport)::-webkit-scrollbar {
  width: 8px;
}

.console-viewer :deep(.xterm-viewport)::-webkit-scrollbar-track {
  background: transparent;
}

.console-viewer :deep(.xterm-viewport)::-webkit-scrollbar-thumb {
  background: #333;
  border-radius: 4px;
}

.console-viewer :deep(.xterm-viewport)::-webkit-scrollbar-thumb:hover {
  background: #555;
}
</style>
