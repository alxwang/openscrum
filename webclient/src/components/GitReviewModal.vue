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
                The agent has modified files. Please accept or reject these changes to continue.
              </p>
            </div>
          </div>
          
          <div class="text-sm font-medium px-3 py-1 rounded-full bg-white/5 text-gray-300 flex border border-white/10">
            <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-green-500"></span> Additions</span>
            <span class="mx-3 text-white/20">|</span>
            <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-red-500"></span> Deletions</span>
          </div>
        </div>

        <!-- Body / Diff Viewer -->
        <div class="px-6 py-4 max-h-[60vh] overflow-y-auto bg-[#1e1e1e]">
          <Diff
            :mode="diffMode"
            :theme="'dark'"
            :language="'javascript'"
            :prev="''"
            :current="diffContent"
            :virtual-scroll="{ height: 400 }"
          />
        </div>

        <!-- Footer -->
        <div class="bg-surface border-t border-white/5 px-6 py-4 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <button 
              @click="diffMode = diffMode === 'split' ? 'unified' : 'split'"
              class="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors border border-white/5"
            >
              Toggle {{ diffMode === 'split' ? 'Unified' : 'Split' }} View
            </button>
          </div>
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
import { ref } from 'vue'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
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

const diffMode = ref('split')
</script>

<style>
/* Adjust vue-diff container to match our dark theme seamlessly */
.vue-diff-wrapper {
  background-color: transparent !important;
  border: none !important;
}
</style>
