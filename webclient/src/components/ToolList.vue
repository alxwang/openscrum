<template>
  <div class="h-full flex flex-col">
    <!-- Tool List Header -->
    <div class="px-4 py-2 border-b border-surface-dark">
      <h3 class="text-sm font-semibold text-text-inverse">Tool Executions</h3>
      <p class="text-xs text-text-muted">{{ tools.length }} tool{{ tools.length !== 1 ? 's' : '' }} executed</p>
    </div>
    
    <!-- Tool List -->
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <div v-if="tools.length === 0" class="p-4 text-center text-text-muted text-sm">
        No tools executed yet
      </div>
      <div v-else class="divide-y divide-surface-dark">
        <div
          v-for="(tool, index) in tools"
          :key="index"
          @click="$emit('select', tool)"
          :class="[
            'px-4 py-3 cursor-pointer transition-colors',
            selectedTool === tool ? 'bg-accent/20 border-l-2 border-accent' : 'hover:bg-surface-dark/50'
          ]"
        >
          <!-- Tool Name -->
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-medium text-text-inverse">{{ tool.name }}</span>
            <span :class="[
              'text-xs px-2 py-0.5 rounded',
              tool.status === 'completed' ? 'bg-green-600/20 text-green-400' :
              tool.status === 'pending' ? 'bg-yellow-600/20 text-yellow-400' :
              'bg-red-600/20 text-red-400'
            ]">
              {{ tool.status }}
            </span>
          </div>
          
          <!-- Tool Input Summary -->
          <div v-if="tool.input" class="text-xs text-text-muted truncate">
            {{ formatInput(tool.input) }}
          </div>
          
          <!-- Timestamp -->
          <div class="text-xs text-text-muted/70 mt-1">
            {{ formatTime(tool.timestamp) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue'

const props = defineProps({
  tools: {
    type: Array,
    default: () => []
  },
  selectedTool: {
    type: Object,
    default: null
  }
})

defineEmits(['select'])

const formatInput = (input) => {
  if (!input) return ''
  
  if (typeof input === 'string') {
    return input.length > 100 ? input.substring(0, 100) + '...' : input
  }
  
  if (typeof input === 'object') {
    // For bash commands, show the command
    if (input.command) {
      return input.command.length > 100 ? input.command.substring(0, 100) + '...' : input.command
    }
    // For other objects, show JSON
    const json = JSON.stringify(input)
    return json.length > 100 ? json.substring(0, 100) + '...' : json
  }
  
  return String(input)
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString()
}
</script>
