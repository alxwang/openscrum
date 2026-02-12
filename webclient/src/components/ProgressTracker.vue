<template>
  <div class="progress-tracker bg-surface-dark rounded-lg p-3 my-2 border border-surface">
    <!-- Header -->
    <div class="flex items-center gap-2 mb-3">
      <div class="h-5 w-5 rounded-full bg-accent flex items-center justify-center flex-shrink-0">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
      </div>
      <h3 class="text-base font-semibold text-text-inverse">Execution Plan</h3>
    </div>

    <!-- Steps List -->
    <div class="space-y-1.5">
      <div
        v-for="(stepTitle, stepNum) in sortedSteps"
        :key="stepNum"
        :class="[
          'flex items-start gap-2 p-2 rounded-lg transition-colors',
          getStepClass(parseInt(stepNum))
        ]"
      >
        <!-- Step Indicator -->
        <div class="flex-shrink-0 mt-0.5">
          <div
            :class="[
              'h-5 w-5 rounded-full flex items-center justify-center text-xs font-bold',
              getStepIndicatorClass(parseInt(stepNum))
            ]"
          >
            <svg v-if="parseInt(stepNum) < currentStep" xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
            </svg>
            <span v-else class="text-xs">{{ stepNum }}</span>
          </div>
        </div>

        <!-- Step Content -->
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-gray-900">
            {{ stepTitle }}
          </p>
          
          <!-- Current Step Status -->
          <div v-if="parseInt(stepNum) === currentStep && status" class="mt-1.5">
            <div class="flex items-start gap-2">
              <div class="animate-spin h-3 w-3 border-2 border-accent border-t-transparent rounded-full mt-0.5 flex-shrink-0"></div>
              <p class="text-xs text-accent">{{ status }}</p>
            </div>
            <p v-if="nextStep" class="text-xs text-text-muted mt-1 ml-5">
              Next: {{ nextStep }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Progress Bar -->
    <div class="mt-3 pt-3 border-t border-surface">
      <div class="flex items-center justify-between text-xs mb-1.5">
        <span class="text-text-muted">Progress</span>
        <span class="text-text-inverse font-medium">{{ progressPercentage }}%</span>
      </div>
      <div class="h-1.5 bg-background-dark rounded-full overflow-hidden">
        <div 
          class="h-full bg-accent rounded-full transition-all duration-500"
          :style="{ width: progressPercentage + '%' }"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  plan: {
    type: Object,
    required: true,
  },
  currentProgress: {
    type: Object,
    required: true,
  },
})

// Sort steps by number
const sortedSteps = computed(() => {
  const steps = { ...props.plan }
  const sortedKeys = Object.keys(steps).sort((a, b) => parseInt(a) - parseInt(b))
  const sorted = {}
  sortedKeys.forEach(key => {
    sorted[key] = steps[key]
  })
  return sorted
})

const currentStep = computed(() => props.currentProgress.step || 0)
const status = computed(() => props.currentProgress.status || '')
const nextStep = computed(() => props.currentProgress.next_step || '')

const totalSteps = computed(() => Object.keys(props.plan).length)
const completedSteps = computed(() => Math.max(0, currentStep.value - 1))
const progressPercentage = computed(() => {
  if (totalSteps.value === 0) return 0
  const percentage = Math.round((completedSteps.value / totalSteps.value) * 100)
  return isNaN(percentage) ? 0 : percentage
})

const getStepClass = (stepNum) => {
  if (stepNum === currentStep.value) {
    return 'bg-accent/10 border border-accent'
  } else if (stepNum < currentStep.value) {
    return 'bg-surface opacity-60'
  }
  return 'bg-surface/50'
}

const getStepIndicatorClass = (stepNum) => {
  if (stepNum === currentStep.value) {
    return 'bg-accent text-white border-2 border-accent'
  } else if (stepNum < currentStep.value) {
    return 'bg-green-600 text-white'
  }
  return 'bg-surface text-text-muted border border-surface-dark'
}
</script>

<style scoped>
.progress-tracker {
  animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
