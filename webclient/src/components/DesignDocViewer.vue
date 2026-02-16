<template>
  <div class="design-doc-viewer h-full flex flex-col bg-surface/30">
    <!-- Header with edit controls -->
    <div class="px-4 py-3 border-b border-surface-dark flex items-center justify-between">
      <div>
        <h3 class="text-sm font-semibold text-text-inverse">{{ docInfo?.name || 'Select a document' }}</h3>
        <p v-if="docInfo" class="text-xs text-text-muted mt-0.5">{{ docInfo.description }}</p>
      </div>
      <div v-if="hasContent" class="flex items-center gap-2">
        <button
          v-if="!isEditing"
          @click="startEditing"
          class="px-3 py-1.5 text-xs rounded-lg bg-accent hover:bg-accent-hover transition-colors"
        >
          Edit
        </button>
        <template v-else>
          <button
            @click="cancelEditing"
            class="px-3 py-1.5 text-xs rounded-lg bg-surface-dark hover:bg-surface transition-colors"
          >
            Cancel
          </button>
          <button
            @click="saveChanges"
            :disabled="!hasChanges"
            class="px-3 py-1.5 text-xs rounded-lg bg-green-600 hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Save
          </button>
        </template>
      </div>
    </div>
    
    <!-- Content area -->
    <div class="flex-1 overflow-hidden">
      <!-- Empty state -->
      <div v-if="!hasContent" class="flex items-center justify-center h-full text-text-muted px-4">
        <div class="text-center max-w-md">
          <p class="text-sm">{{ docType ? 'This document hasn\'t been created yet.' : 'Select a document from the list to view or edit.' }}</p>
          <p v-if="docType" class="text-xs mt-2">Ask the agent to create it using the design_create tool.</p>
        </div>
      </div>
      
      <!-- Edit mode -->
      <div v-else-if="isEditing" class="h-full flex flex-col">
        <textarea
          v-model="editContent"
          class="flex-1 w-full px-4 py-3 bg-white text-gray-900 font-mono text-sm resize-none focus:outline-none border border-gray-200"
          style="font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;"
        ></textarea>
        <div class="px-4 py-2 bg-gray-50 border-t border-gray-200 text-xs text-gray-600">
          Markdown format • Changes auto-save
        </div>
      </div>
      
      <!-- View mode (rendered markdown) -->
      <div v-else class="h-full overflow-y-auto custom-scrollbar px-6 py-4 bg-white">
        <div class="prose max-w-none" v-html="renderedContent"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

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
  docType: {
    type: String,
    default: null
  },
  docInfo: {
    type: Object,
    default: null
  },
  content: {
    type: String,
    default: null
  }
})

const emit = defineEmits(['save'])

const isEditing = ref(false)
const editContent = ref('')
const originalContent = ref('')

const hasContent = computed(() => props.content !== null && props.content !== undefined)
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

// Watch for doc type changes
watch(() => props.docType, () => {
  isEditing.value = false
})

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
  
  emit('save', {
    docType: props.docType,
    content: editContent.value
  })
  
  originalContent.value = editContent.value
  isEditing.value = false
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
  color: #1a202c;
}

:deep(.prose h1),
:deep(.prose h2),
:deep(.prose h3),
:deep(.prose h4),
:deep(.prose h5),
:deep(.prose h6) {
  color: #000000;
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
  border-bottom: 1px solid #e2e8f0;
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
  background-color: #f7fafc;
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.875rem;
  color: #c53030;
  border: 1px solid #e2e8f0;
}

:deep(.prose pre) {
  background-color: #f7fafc;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin-top: 1rem;
  margin-bottom: 1rem;
  border: 1px solid #e2e8f0;
}

:deep(.prose pre code) {
  background-color: transparent;
  padding: 0;
  color: #1a202c;
  font-size: 0.875rem;
  border: none;
}

:deep(.prose a) {
  color: #2563eb;
  text-decoration: underline;
}

:deep(.prose a:hover) {
  color: #1d4ed8;
}

:deep(.prose blockquote) {
  border-left: 4px solid #cbd5e0;
  padding-left: 1rem;
  margin-left: 0;
  font-style: italic;
  color: #4a5568;
}

:deep(.prose table) {
  width: 100%;
  margin-top: 1rem;
  margin-bottom: 1rem;
  border-collapse: collapse;
}

:deep(.prose th) {
  background-color: #f7fafc;
  padding: 0.5rem;
  text-align: left;
  font-weight: 600;
  border: 1px solid #e2e8f0;
  color: #000000;
}

:deep(.prose td) {
  padding: 0.5rem;
  border: 1px solid #e2e8f0;
  color: #1a202c;
}

:deep(.prose tr:nth-child(even)) {
  background-color: #f7fafc;
}
</style>
