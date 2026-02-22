<template>
  <div class="code-viewer flex flex-col h-full bg-surface-dark text-gray-200 w-full mx-auto shadow-2xl overflow-hidden transition-all duration-300">
    <!-- Header -->
    <div class="flex-shrink-0 flex items-center justify-between px-6 py-4 bg-surface border-b border-surface-dark">
      <div class="flex items-center gap-3 w-full max-w-full min-w-0">
        <!-- Close Button -->
        <button 
          @click="$emit('close')"
          class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-800 text-gray-400 hover:text-gray-100 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-accent"
          title="Close file"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M3 10a.75.75 0 01.75-.75h10.638L10.23 5.29a.75.75 0 111.04-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.04-1.08l4.158-3.96H3.75A.75.75 0 013 10z" clip-rule="evenodd" transform="rotate(180 10 10)" />
          </svg>
        </button>

        <!-- Dynamic Title -->
        <h2 class="text-lg font-semibold text-gray-100 truncate overflow-hidden text-ellipsis w-full">
          {{ fileName }}
        </h2>
      </div>
    </div>

    <!-- Content Area -->
    <div class="flex-1 overflow-auto custom-scrollbar relative bg-background-darker">
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-background-darker/50 backdrop-blur-sm z-10 transition-opacity duration-300">
        <div class="flex flex-col items-center gap-4">
          <div class="w-8 h-8 border-4 border-accent border-t-transparent rounded-full animate-spin"></div>
          <p class="text-text-muted text-sm font-medium animate-pulse">Loading file contents...</p>
        </div>
      </div>
      
      <!-- Highlight.js Code Block -->
      <pre v-if="content && !loading" class="h-full w-full !m-0 !bg-transparent whitespace-pre-wrap break-words"><code :class="['language-' + language, '!bg-transparent !p-6 text-sm whitespace-pre-wrap break-words inline-block w-full']" v-html="highlightedContent"></code></pre>
      
      <!-- Empty/Error State -->
      <div v-if="!content && !loading && !error" class="h-full flex items-center justify-center text-gray-400">
        <div class="text-center">
          <p class="text-sm">File is empty</p>
        </div>
      </div>
      
      <div v-if="error && !loading" class="h-full flex items-center justify-center text-red-500">
        <div class="text-center">
          <p class="text-sm">{{ error }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css' // Import a nice light theme

const props = defineProps({
  path: {
    type: String,
    required: true
  },
  content: {
    type: String,
    default: ''
  },
  loading: {
    type: Boolean,
    default: false
  },
  error: {
    type: String,
    default: null
  }
})

defineEmits(['close'])

const fileName = computed(() => {
  if (!props.path) return 'Unknown File'
  const parts = props.path.split('/')
  return parts[parts.length - 1]
})

const language = computed(() => {
  if (!fileName.value) return 'plaintext'
  const ext = fileName.value.split('.').pop().toLowerCase()
  
  // Map common extensions to highlight.js aliases
  const extMap = {
    'js': 'javascript',
    'jsx': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'vue': 'html',
    'py': 'python',
    'json': 'json',
    'md': 'markdown',
    'html': 'html',
    'css': 'css',
    'sh': 'bash',
    'yaml': 'yaml',
    'yml': 'yaml',
    'prisma': 'graphql', // highlight.js doesn't natively support prisma, graphql looks okay
    'sql': 'sql',
    'go': 'go',
    'java': 'java',
    'cpp': 'cpp',
    'c': 'c'
  }
  
  return extMap[ext] || 'plaintext'
})

const highlightedContent = computed(() => {
  if (!props.content) return ''
  try {
    return hljs.highlight(props.content, { language: language.value }).value
  } catch (e) {
    console.warn('Highlighting failed, falling back to plaintext', e)
    return hljs.highlight(props.content, { language: 'plaintext' }).value
  }
})
</script>
