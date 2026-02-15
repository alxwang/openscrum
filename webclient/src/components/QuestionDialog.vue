<template>
  <div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
        <h2 class="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <svg class="w-6 h-6 text-cyan-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {{ questionData.title || 'Agent has questions for you' }}
        </h2>
        <p v-if="questionData.description" class="text-sm text-gray-600 mt-1">{{ questionData.description }}</p>
        <p v-else class="text-sm text-gray-600 mt-1">Please provide answers to help the agent proceed</p>
      </div>

      <!-- Questions -->
      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-5 question-scroll">
        <div v-for="(question, index) in questionData.questions" :key="question.id || index" class="space-y-2">
          <label class="block text-sm font-medium text-gray-900">
            {{ question.question }}
            <span v-if="question.required" class="text-cyan-500">*</span>
          </label>
          
          <!-- Text Input -->
          <input
            v-if="question.type === 'text'"
            v-model="answers[question.id]"
            :placeholder="question.placeholder || 'Your answer...'"
            type="text"
            class="w-full px-4 py-2 bg-white text-gray-900 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-cyan-500"
          />
          
          <!-- Textarea Input -->
          <textarea
            v-else-if="question.type === 'textarea'"
            v-model="answers[question.id]"
            :placeholder="question.placeholder || 'Your answer...'"
            class="w-full px-4 py-2 bg-white text-gray-900 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-cyan-500 resize-none"
            rows="3"
            @keydown.meta.enter="handleSubmit"
            @keydown.ctrl.enter="handleSubmit"
          ></textarea>
          
          <!-- Number Input -->
          <input
            v-else-if="question.type === 'number'"
            v-model.number="answers[question.id]"
            :placeholder="question.placeholder  || question.default?.toString() || 'Enter number...'"
            :min="question.min"
            :max="question.max"
            type="number"
            class="w-full px-4 py-2 bg-white text-gray-900 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-cyan-500"
          />
          
          <!-- Single Choice -->
          <select
            v-else-if="question.type === 'choice'"
            v-model="answers[question.id]"
            class="w-full px-4 py-2 bg-white text-gray-900 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-cyan-500"
          >
            <option value="">-- Select an option --</option>
            <option v-for="option in question.options" :key="option" :value="option">
              {{ option }}
            </option>
          </select>
          
          <!-- Multiple Choice -->
          <div v-else-if="question.type === 'multichoice'" class="space-y-2">
            <label
              v-for="option in question.options"
              :key="option"
              class="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-100 cursor-pointer"
            >
              <input
                type="checkbox"
                :value="option"
                v-model="answers[question.id]"
                class="w-4 h-4 rounded border-gray-300 bg-white text-cyan-500 focus:ring-2 focus:ring-cyan-500"
              />
              <span class="text-sm text-gray-900">{{ option }}</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-between items-center">
        <span class="text-xs text-gray-600">
          <span class="text-cyan-500">*</span> Required fields
        </span>
        <div class="flex gap-3">
          <button
            v-if="!hasRequiredQuestions"
            @click="handleSkip"
            class="px-4 py-2 rounded-lg bg-gray-200 hover:bg-gray-300 text-gray-700 hover:text-gray-900 transition-colors"
          >
            Skip
          </button>
          <button
            @click="handleSubmit"
            :disabled="!canSubmit"
            class="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
          >
            Submit Answers {{ canSubmit ? '(⌘/Ctrl+Enter)' : '' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const props = defineProps({
  questionData: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['submit', 'skip'])

const answers = ref({})

// Initialize answers with defaults from questions
onMounted(() => {
  if (!props.questionData?.questions) return
  
  props.questionData.questions.forEach(q => {
    // Handle defaults for all question types
    if (q.default !== undefined && q.default !== null) {
      if (q.type === 'multichoice') {
        // Ensure multichoice default is an array
        answers.value[q.id] = Array.isArray(q.default) ? [...q.default] : [q.default]
      } else {
        answers.value[q.id] = q.default
      }
    } else if (q.type === 'multichoice') {
      // Initialize empty array for multichoice if no default
      answers.value[q.id] = []
    }
  })
})

const hasRequiredQuestions = computed(() => {
  return props.questionData.questions.some(q => q.required)
})

const canSubmit = computed(() => {
  // Check if all required questions have answers
  return props.questionData.questions.every(q => {
    if (!q.required) return true
    
    const answer = answers.value[q.id]
    if (q.type === 'multichoice') {
      return Array.isArray(answer) && answer.length > 0
    }
    return answer !== undefined && answer !== null && answer !== ''
  })
})

const handleSubmit = () => {
  if (!canSubmit.value) return
  
  // Return answers as JSON object
  emit('submit', answers.value)
}

const handleSkip = () => {
  emit('skip')
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
  background-color: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: rgba(255, 255, 255, 0.3);
}

/* Light theme scrollbar for question dialog */
.question-scroll::-webkit-scrollbar {
  width: 8px;
}

.question-scroll::-webkit-scrollbar-track {
  background: #f3f4f6;
}

.question-scroll::-webkit-scrollbar-thumb {
  background-color: #d1d5db;
  border-radius: 4px;
}

.question-scroll::-webkit-scrollbar-thumb:hover {
  background-color: #9ca3af;
}
</style>
