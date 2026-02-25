<template>
  <div class="todo-list h-full flex flex-col bg-surface/30">
    <!-- Header with Generate Button -->
    <div class="px-4 py-3 border-b border-surface-dark bg-surface/50 flex justify-between items-center">
      <div>
        <h3 class="text-sm font-semibold text-text-inverse">Execution Plan</h3>
        <p class="text-xs text-text-muted mt-1">Agent's tasks for current phase</p>
      </div>
      <button 
        @click="$emit('generate')" 
        :disabled="isGenerating"
        class="p-1.5 bg-surface-dark hover:bg-surface-dark/80 rounded border border-surface-dark transition-colors flex items-center gap-1 text-xs"
        title="Auto-generate tasks from Design Docs"
      >
        <svg v-if="isGenerating" class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span>Generate</span>
      </button>
    </div>
    
    <div class="flex-1 overflow-y-auto custom-scrollbar p-0 relative">
      <div v-if="!todos || todos.length === 0" class="flex flex-col items-center justify-center h-full text-text-muted px-4 text-center">
        <div class="w-8 h-8 rounded-full bg-surface-dark flex items-center justify-center mb-3">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
        </div>
        <p class="text-sm pb-2">No active tasks</p>
        <button 
          v-if="!isGenerating"
          @click="$emit('generate')"
          class="px-3 py-1.5 bg-accent text-white rounded text-xs mt-2 hover:bg-accent/90 transition-colors"
        >
          Auto-Generate Tasks
        </button>
      </div>
      
      <div v-else class="flex flex-col">
        <!-- Progress Bar at top -->
        <div class="bg-surface border-b border-surface-dark px-4 py-2 sticky top-0 z-10">
          <div class="flex items-center justify-between text-xs mb-1.5">
            <span class="text-text-muted">Overall Progress</span>
            <span class="text-text-inverse font-medium">{{ progressPercentage }}%</span>
          </div>
          <div class="h-1.5 bg-background-dark rounded-full overflow-hidden">
            <div 
              class="h-full bg-accent rounded-full transition-all duration-500"
              :style="{ width: progressPercentage + '%' }"
            ></div>
          </div>
        </div>

        <!-- Task List Items -->
        <div class="divide-y divide-surface-dark">
          <div 
            v-for="(todo, index) in sortedTodos" 
            :key="todo.id"
            class="px-4 py-3 transition-colors duration-200 cursor-pointer relative group"
            :class="[
              getStepBackgroundClass(todo),
              todo.status === 'in_progress' 
                ? 'hover:bg-gray-700/80' 
                : (selectedId === todo.id ? 'bg-surface ring-1 ring-inset ring-surface-dark' : 'hover:bg-surface/50')
            ]"
            @click="selectedId = selectedId === todo.id ? null : todo.id"
          >
            <!-- Delete Button (Shown on hover) -->
            <button 
              @click.stop="$emit('delete', todo.id)"
              class="absolute top-3 right-3 p-1.5 text-text-muted hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity bg-surface/80 rounded"
              title="Delete task"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>

            <div class="flex items-start gap-3 pr-6">
              <!-- Checkbox / Status Icon -->
              <div class="flex-shrink-0 mt-0.5">
                <div 
                  class="w-5 h-5 rounded flex items-center justify-center border transition-colors"
                  :class="getIconContainerClass(todo)"
                >
                  <svg v-if="todo.status === 'completed'" xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-white" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                  </svg>
                  <div v-else-if="todo.status === 'in_progress'" class="flex items-center justify-center">
                    <svg class="animate-spin h-3.5 w-3.5 text-accent" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  </div>
                  <span v-else class="text-[9px] font-medium text-text-muted overflow-hidden whitespace-nowrap">{{ getStepBadgeText(todo, index) }}</span>
                </div>
              </div>
              
              <!-- Content -->
              <div class="flex-1 min-w-0">
                <p 
                  class="text-sm font-medium pr-4" 
                  :class="todo.status === 'completed' ? 'text-gray-400 line-through' : (todo.status === 'in_progress' ? 'text-text-inverse' : 'text-gray-800')"
                >
                  {{ todo.content }}
                </p>
                
                <!-- Expanded Selection View -->
                <div v-if="selectedId === todo.id" class="mt-3 flex gap-2">
                  <button 
                    @click.stop="$emit('process', todo)"
                    :disabled="isAnyTaskProcessing"
                    class="px-3 py-1.5 rounded text-xs transition-colors flex items-center gap-1.5"
                    :class="isAnyTaskProcessing ? 'bg-surface-dark text-text-muted cursor-not-allowed opacity-50' : 'bg-accent text-white hover:bg-accent/90'"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Process Task
                  </button>
                  <span v-if="isAnyTaskProcessing && todo.status !== 'in_progress'" class="text-xs text-yellow-500 self-center ml-2">Another task is currently processing</span>
                </div>
                
                <!-- Active Step Details (only for in_progress items from tracker progress) -->
                <div v-if="todo.status === 'in_progress' && status" class="mt-2 text-xs">
                  <div class="inline-flex items-center px-2 py-1 rounded bg-black/30 border border-surface-dark gap-2">
                    <div v-if="isActiveStatus" class="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin"></div>
                    <span :class="isActiveStatus ? 'text-accent' : 'text-green-500'">{{ status }}</span>
                  </div>
                  
                  <div v-if="nextStep" class="mt-2 text-text-muted flex items-start gap-1 p-2 bg-surface rounded-md border border-surface-dark">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                    </svg>
                    <span class="leading-tight">{{ nextStep }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  todos: {
    type: Array,
    default: () => []
  },
  currentProgress: {
    type: Object,
    default: () => ({})
  },
  isGenerating: {
    type: Boolean,
    default: false
  }
})

defineEmits(['generate', 'delete', 'process'])

const selectedId = ref(null)

// Sort steps by logically extracted #num prefix, fallback to ID
const sortedTodos = computed(() => {
  if (!props.todos) return []
  return [...props.todos].sort((a, b) => {
    const matchA = a.content?.match(/^#(\d+)/)
    const matchB = b.content?.match(/^#(\d+)/)
    
    if (matchA && matchB) {
      return parseInt(matchA[1]) - parseInt(matchB[1])
    }
    
    // Fallback if numbers aren't found for whatever reason
    const idA = parseInt(a.id)
    const idB = parseInt(b.id)
    if (!isNaN(idA) && !isNaN(idB)) {
      return idA - idB
    }
    return String(a.id).localeCompare(String(b.id))
  })
})

const status = computed(() => props.currentProgress?.status || '')
const nextStep = computed(() => props.currentProgress?.next_step || '')

// Determine if ANY task is currently processing anywhere in the list
const isAnyTaskProcessing = computed(() => {
  return props.todos && props.todos.some(t => t.status === 'in_progress')
})

// Check if status indicates active work
const isActiveStatus = computed(() => {
  if (!status.value) return false
  const statusLower = status.value.toLowerCase()
  const completionWords = ['succeeded', 'completed', 'finished', 'ready', 'done', 'success']
  if (completionWords.some(word => statusLower.includes(word))) return false
  return true
})

const totalSteps = computed(() => props.todos?.length || 0)
const completedSteps = computed(() => props.todos?.filter(t => t.status === 'completed').length || 0)
const progressPercentage = computed(() => {
  if (totalSteps.value === 0) return 0
  const percentage = Math.round((completedSteps.value / totalSteps.value) * 100)
  return isNaN(percentage) ? 0 : percentage
})

const getStepBackgroundClass = (todo) => {
  if (todo.status === 'in_progress') return 'bg-gray-800/80 ring-1 ring-inset ring-accent shadow-inner'
  if (todo.status === 'completed') return 'bg-surface/30'
  return 'bg-transparent'
}

const getIconContainerClass = (todo) => {
  if (todo.status === 'in_progress') return 'border-accent bg-accent/20'
  if (todo.status === 'completed') return 'border-green-600 bg-green-600'
  return 'border-surface-dark bg-surface-dark/50'
}

const getStepBadgeText = (todo, index) => {
  const match = todo?.content?.match(/^#(\d+)/)
  if (match && match[1]) return match[1]
  return String(index + 1)
}
</script>
