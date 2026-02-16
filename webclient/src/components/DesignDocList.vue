<template>
  <div class="design-doc-list h-full flex flex-col bg-surface/50">
    <!-- Header -->
    <div class="px-4 py-3 border-b border-surface-dark">
      <h3 class="text-sm font-semibold text-text-inverse">Design Documents</h3>
      <p class="text-xs text-text-muted mt-1">Click a document to view/edit</p>
    </div>
    
    <!-- Document list -->
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <div class="p-2 space-y-1">
        <button
          v-for="(doc, docType) in documents"
          :key="docType"
          @click="$emit('select', docType)"
          :class="[
            'w-full text-left px-3 py-2 rounded-lg transition-colors',
            selectedDoc === docType 
              ? 'bg-accent text-text-inverse' 
              : 'bg-surface-dark hover:bg-surface text-text'
          ]"
        >
          <div class="flex items-center gap-2">
            <span :class="doc.exists ? 'text-green-400' : 'text-text-muted'">
              {{ doc.exists ? '✓' : '○' }}
            </span>
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm">{{ doc.name }}</div>
              <div class="text-xs text-text-muted truncate">{{ doc.description }}</div>
              <div v-if="doc.exists && doc.last_modified" class="text-xs text-text-muted mt-0.5">
                Modified: {{ formatDate(doc.last_modified) }}
              </div>
            </div>
          </div>
        </button>
      </div>
      
      <!-- Empty state -->
      <div v-if="Object.keys(documents).length === 0" class="p-4 text-center text-text-muted text-sm">
        <p>No design documents yet.</p>
        <p class="mt-2">Ask the agent to create design documents in Plan Mode.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue'

defineProps({
  documents: {
    type: Object,
    default: () => ({})
  },
  selectedDoc: {
    type: String,
    default: null
  }
})

defineEmits(['select'])

const formatDate = (dateStr) => {
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateStr
  }
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
</style>
