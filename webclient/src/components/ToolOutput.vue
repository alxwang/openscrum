<template>
  <div class="h-full flex flex-col bg-background-dark">
    <div v-if="tool" class="h-full flex flex-col">
      <!-- Tool Header -->
      <div class="px-4 py-3 border-b border-surface-dark">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-text-inverse">{{ tool.name }}</h3>
          <span :class="[
            'text-xs px-2 py-1 rounded font-medium',
            tool.status === 'completed' ? 'bg-green-600/20 text-green-400' :
            tool.status === 'pending' ? 'bg-yellow-600/20 text-yellow-400' :
            'bg-red-600/20 text-red-400'
          ]">
            {{ tool.status }}
          </span>
        </div>
        <div class="text-xs text-text-muted">
          {{ formatTime(tool.timestamp) }}
        </div>
      </div>
      
      <!-- Tool Input -->
      <div v-if="tool.input" class="border-b border-surface-dark">
        <div class="px-4 py-2 bg-surface-dark/30">
          <h4 class="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">Input</h4>
          <pre class="text-xs text-text-inverse bg-background rounded p-2 overflow-x-auto custom-scrollbar">{{ formatInput(tool.input) }}</pre>
        </div>
      </div>
      
      <!-- Tool Output -->
      <div class="flex-1 overflow-hidden flex flex-col">
        <div class="px-4 py-2 bg-surface-dark/30 border-b border-surface-dark">
          <h4 class="text-xs font-semibold text-text-muted uppercase tracking-wider">Output</h4>
        </div>
        <div class="flex-1 overflow-y-auto custom-scrollbar">
          <div v-if="tool.output" class="p-4">
            <pre class="text-xs text-text-inverse whitespace-pre-wrap break-words">{{ tool.output }}</pre>
          </div>
          <div v-else-if="tool.status === 'pending'" class="p-4 text-center">
            <div class="inline-flex items-center gap-2 text-text-muted">
              <div class="animate-spin h-4 w-4 border-2 border-accent border-t-transparent rounded-full"></div>
              <span class="text-sm">Waiting for execution...</span>
            </div>
          </div>
          <div v-else class="p-4 text-center text-text-muted text-sm">
            No output available
          </div>
        </div>
      </div>
    </div>
    
    <!-- Empty State -->
    <div v-else class="h-full flex items-center justify-center text-text-muted text-sm">
      <div class="text-center">
        <svg class="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
        </svg>
        <p>Select a tool to view details</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps } from 'vue'

defineProps({
  tool: {
    type: Object,
    default: null
  }
})

const formatInput = (input) => {
  if (!input) return ''
  
  if (typeof input === 'string') {
    return input
  }
  
  if (typeof input === 'object') {
    return JSON.stringify(input, null, 2)
  }
  
  return String(input)
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleString()
}
</script>
