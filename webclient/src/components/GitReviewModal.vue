<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
      
      <!-- Background overlay -->
      <div 
        class="fixed inset-0 bg-black/70 transition-opacity backdrop-blur-sm" 
        aria-hidden="true"
      ></div>

      <!-- Center modal trick -->
      <span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="relative inline-block align-bottom bg-surface-dark border border-white/10 rounded-xl text-left overflow-hidden shadow-2xl transform transition-all sm:my-8 sm:align-middle w-full max-w-5xl">
        
        <!-- Header -->
        <div class="bg-surface border-b border-white/5 px-6 py-4 flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-accent/20 rounded-lg text-accent">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </div>
            <div>
              <h3 class="text-lg font-medium tracking-tight text-white" id="modal-title">
                Review Agent Changes
              </h3>
              <p class="text-sm text-gray-400 mt-0.5">
                Review all changed files before accepting or rejecting.
              </p>
            </div>
          </div>
          
          <div class="text-sm font-medium px-3 py-1 rounded-full bg-white/5 text-gray-300 flex border border-white/10">
            <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-green-500"></span> Additions</span>
            <span class="mx-3 text-white/20">|</span>
            <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-red-500"></span> Deletions</span>
          </div>
        </div>

        <!-- Body / Split File List + Diff Viewer -->
        <div class="px-6 py-4 h-[60vh] bg-[#1e1e1e]">
          <div class="h-full grid grid-cols-[280px_1fr] gap-4">
            <aside class="h-full border border-white/10 rounded-lg bg-surface overflow-hidden flex flex-col">
              <div class="px-3 py-2 border-b border-white/10 text-xs text-black font-medium bg-white">
                Changed Files ({{ normalizedFiles.length }})
              </div>
              <div class="flex-1 overflow-y-auto">
                <button
                  v-for="file in normalizedFiles"
                  :key="file.path"
                  @click="selectedPath = file.path"
                  class="w-full text-left px-3 py-2 border-b border-white/5 hover:bg-white/80 transition-colors bg-white"
                  :class="selectedPath === file.path ? 'bg-white' : ''"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-xs text-black truncate">{{ file.path }}</span>
                    <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="statusBadgeClass(file.status)">
                      {{ file.status || 'M' }}
                    </span>
                  </div>
                </button>
              </div>
            </aside>

            <section class="h-full border border-white/10 rounded-lg bg-[#111111] overflow-hidden flex flex-col">
              <div class="px-3 py-2 border-b border-white/10 text-xs text-gray-300 font-medium">
                {{ selectedFile?.path || 'No file selected' }}
              </div>
              <div class="flex-1 overflow-auto p-3">
                <pre class="m-0 text-xs leading-5 font-mono whitespace-pre-wrap break-words text-gray-200"><template v-for="(line, idx) in selectedDiffLines" :key="idx"><div :class="diffLineClass(line)">{{ line || ' ' }}</div></template></pre>
              </div>
            </section>
          </div>
        </div>

        <!-- Footer -->
        <div class="bg-surface border-t border-white/5 px-6 py-4 flex items-center justify-between">
          <div class="text-xs text-gray-400">Patch view</div>
          <div class="flex gap-3">
            <button 
              type="button" 
              @click="$emit('reject')"
              :disabled="isProcessing"
              class="inline-flex items-center px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/20 rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500/40 disabled:opacity-50"
            >
              <svg v-if="!isProcessing" class="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Reject & Revert
            </button>
            <button 
              type="button" 
              @click="$emit('accept')"
              :disabled="isProcessing"
              class="inline-flex items-center px-5 py-2 bg-accent hover:bg-accent/90 text-white border border-accent rounded-lg text-sm font-medium shadow-lg shadow-accent/20 transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-50"
            >
              <svg v-if="isProcessing" class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
              {{ isProcessing ? 'Committing...' : 'Accept Changes' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  changedFiles: {
    type: Array,
    default: () => []
  },
  diffContent: {
    type: String,
    default: ''
  },
  isProcessing: {
    type: Boolean,
    default: false
  }
})

defineEmits(['accept', 'reject'])
const selectedPath = ref('')

const normalizedFiles = computed(() => {
  if (Array.isArray(props.changedFiles) && props.changedFiles.length > 0) {
    return props.changedFiles.map((f) => ({
      path: f.path || '(unknown)',
      status: f.status || '',
      diff: f.diff || '',
      untracked: !!f.untracked,
    }))
  }
  if (props.diffContent && props.diffContent.trim()) {
    return [{
      path: 'all-changes.diff',
      status: 'M',
      diff: props.diffContent,
      untracked: false,
    }]
  }
  return []
})

watch(
  () => [props.isOpen, normalizedFiles.value.map((f) => f.path).join('|')],
  () => {
    if (!props.isOpen) return
    if (!normalizedFiles.value.length) {
      selectedPath.value = ''
      return
    }
    if (!selectedPath.value || !normalizedFiles.value.some((f) => f.path === selectedPath.value)) {
      selectedPath.value = normalizedFiles.value[0].path
    }
  },
  { immediate: true }
)

const selectedFile = computed(() => {
  if (!normalizedFiles.value.length) return null
  const picked = normalizedFiles.value.find((f) => f.path === selectedPath.value)
  return picked || normalizedFiles.value[0]
})

const selectedDiff = computed(() => selectedFile.value?.diff || '')
const selectedDiffLines = computed(() => selectedDiff.value.split('\n'))

const statusBadgeClass = (status) => {
  const s = (status || '').trim()
  if (s === '??' || s.startsWith('A')) return 'bg-green-500/15 text-green-300 border-green-500/30'
  if (s.startsWith('D')) return 'bg-red-500/15 text-red-300 border-red-500/30'
  if (s.startsWith('R')) return 'bg-blue-500/15 text-blue-300 border-blue-500/30'
  return 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30'
}

const diffLineClass = (line) => {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-sky-300'
  if (line.startsWith('@@')) return 'text-violet-300'
  if (line.startsWith('+')) return 'bg-green-500/10 text-green-300'
  if (line.startsWith('-')) return 'bg-red-500/10 text-red-300'
  return 'text-gray-200'
}
</script>

<style>
</style>
