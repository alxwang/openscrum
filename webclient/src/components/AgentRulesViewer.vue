<template>
  <div class="agent-rules-viewer h-full flex flex-col bg-surface-dark">
    <!-- Header with edit controls -->
    <div class="px-4 py-3 border-b border-surface flex items-center justify-between bg-surface">
      <div>
        <h3 class="text-sm font-semibold text-text-inverse">Agent.md (Custom Rules)</h3>
        <p class="text-xs text-text-muted mt-0.5">Define custom instructions for the agent in this workspace.</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="!isEditing"
          @click="startEditing"
          class="px-3 py-1.5 text-xs rounded-lg bg-accent hover:bg-accent-hover text-white transition-colors"
        >
          Edit
        </button>
        <template v-else>
          <button
            @click="cancelEditing"
            class="px-3 py-1.5 text-xs rounded-lg bg-surface-dark hover:bg-surface text-text-inverse hover:text-surface-dark transition-colors"
          >
            Cancel
          </button>
          <button
            @click="saveChanges"
            :disabled="!hasChanges"
            class="px-3 py-1.5 text-xs rounded-lg bg-green-600 hover:bg-green-700 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Save
          </button>
        </template>
      </div>
    </div>
    
    <!-- Content area -->
    <div class="flex-1 overflow-hidden">
      <!-- Empty state -->
      <div v-if="!hasContent || content.trim() === ''" class="flex items-center justify-center h-full text-text-muted px-4">
        <div class="text-center max-w-md">
          <p class="text-sm">No custom rules defined yet.</p>
          <p class="text-xs mt-2 mb-4">Click below to generate a starting template for your workspace.</p>
          <button
            @click="prefillTemplate"
            class="px-4 py-2 text-sm rounded-lg bg-accent hover:bg-accent-hover text-white transition-colors"
          >
            Prefill Best Practices
          </button>
        </div>
      </div>
      
      <!-- Edit mode -->
      <div v-else-if="isEditing" class="h-full flex flex-col">
        <textarea
          v-model="editContent"
          class="flex-1 w-full px-4 py-3 bg-background-darker text-text-inverse font-mono text-sm resize-none focus:outline-none border border-surface-dark whitespace-pre-wrap break-words"
          style="font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;"
        ></textarea>
        <div class="px-4 py-2 bg-surface-dark border-t border-surface-dark text-xs text-text-muted">
          Markdown format • Changes auto-save
        </div>
      </div>
      
      <!-- View mode (rendered markdown) -->
      <div v-else class="h-full overflow-y-auto custom-scrollbar px-6 py-4 bg-background-darker">
        <div class="prose max-w-none whitespace-pre-wrap break-words" v-html="renderedContent"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

// Configure marked for code highlighting
marked.setOptions({
  highlight: function(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch (err) {
        console.error('Highlight error:', err)
      }
    }
    return code
  },
  breaks: true,
  gfm: true
})

const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['save'])

const isEditing = ref(false)
const editContent = ref('')
const originalContent = ref('')

const hasContent = computed(() => !!props.content && props.content.trim() !== '')
const hasChanges = computed(() => editContent.value !== originalContent.value)

const renderedContent = computed(() => {
  if (!props.content) return ''
  try {
    return marked.parse(props.content)
  } catch (err) {
    console.error('Markdown parse error:', err)
    return `<pre>${props.content}</pre>`
  }
})

// Watch for content changes
watch(() => props.content, (newContent) => {
  if (!isEditing.value) {
    editContent.value = newContent || ''
    originalContent.value = newContent || ''
  }
}, { immediate: true })

const startEditing = () => {
  editContent.value = props.content || ''
  originalContent.value = props.content || ''
  isEditing.value = true
}

const cancelEditing = () => {
  editContent.value = originalContent.value
  isEditing.value = false
}

const saveChanges = () => {
  if (!hasChanges.value) {
    isEditing.value = false
    return
  }
  
  emit('save', editContent.value)
  
  originalContent.value = editContent.value
  isEditing.value = false
}

const prefillTemplate = () => {
  const template = `# OpenScrum Agent Rules

These rules apply to the agent when operating in **Edit Mode** within this workspace.

## Coding Standards
1. Use semantic HTML and modern CSS (flexbox/grid).
2. Prefer composition over inheritance.
3. Write self-documenting code with clear variable names.

## Verification
- Always test your changes if a test runner is available.
- Verify UI changes visually if applicable.`
  
  editContent.value = template
  originalContent.value = template
  emit('save', template)
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 8px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #4a5568;
  border-radius: 4px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #718096;
}

/* Prose styling for rendered markdown */
:deep(.prose) {
  color: #e2e8f0;
}

:deep(.prose h1),
:deep(.prose h2),
:deep(.prose h3),
:deep(.prose h4),
:deep(.prose h5),
:deep(.prose h6) {
  color: #ffffff;
  font-weight: 600;
}

:deep(.prose h1) {
  font-size: 1.875rem;
  margin-top: 0;
  margin-bottom: 1rem;
}

:deep(.prose h2) {
  font-size: 1.5rem;
  margin-top: 2rem;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #4a5568;
}

:deep(.prose h3) {
  font-size: 1.25rem;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
}

:deep(.prose p) {
  margin-top: 0.75rem;
  margin-bottom: 0.75rem;
  line-height: 1.6;
}

:deep(.prose ul),
:deep(.prose ol) {
  margin-top: 0.75rem;
  margin-bottom: 0.75rem;
  padding-left: 1.5rem;
}

:deep(.prose li) {
  margin-top: 0.25rem;
  margin-bottom: 0.25rem;
}

:deep(.prose code) {
  background-color: #1a202c;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.875rem;
  color: #fc8181;
  border: 1px solid #2d3748;
}

:deep(.prose pre) {
  background-color: #1a202c;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-wrap: break-word;
  word-wrap: break-word;
  white-space: pre-wrap;
  margin-top: 1rem;
  margin-bottom: 1rem;
  border: 1px solid #2d3748;
}

:deep(.prose pre code) {
  background-color: transparent;
  padding: 0;
  color: #e2e8f0;
  font-size: 0.875rem;
  border: none;
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.prose a) {
  color: #63b3ed;
  text-decoration: underline;
}

:deep(.prose a:hover) {
  color: #90cdf4;
}

:deep(.prose blockquote) {
  border-left: 4px solid #4a5568;
  padding-left: 1rem;
  margin-left: 0;
  font-style: italic;
  color: #a0aec0;
}

:deep(.prose table) {
  width: 100%;
  margin-top: 1rem;
  margin-bottom: 1rem;
  border-collapse: collapse;
}

:deep(.prose th) {
  background-color: #1a202c;
  padding: 0.5rem;
  text-align: left;
  font-weight: 600;
  border: 1px solid #2d3748;
  color: #ffffff;
}

:deep(.prose td) {
  padding: 0.5rem;
  border: 1px solid #2d3748;
  color: #e2e8f0;
}

:deep(.prose tr:nth-child(even)) {
  background-color: #1a202c;
}
</style>
