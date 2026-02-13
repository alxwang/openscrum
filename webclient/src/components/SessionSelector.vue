<template>
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="handleClose">
    <div class="bg-background-dark rounded-lg p-6 w-full max-w-2xl max-h-[80vh] flex flex-col border border-surface-dark">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-xl font-semibold text-text-inverse">Select or Create Session</h2>
          <p v-if="!canClose" class="text-sm text-yellow-400 mt-1">You must create or select a session to continue</p>
        </div>
        <button
          v-if="canClose"
          @click="handleClose"
          class="text-text-muted hover:text-text-inverse transition-colors"
          title="Close"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>

      <!-- Create New Session -->
      <div class="mb-6 p-4 bg-surface-dark rounded-lg">
        <h3 class="text-lg font-medium text-text-inverse mb-3">Create New Session</h3>
        <p class="text-sm text-text-muted mb-3">Session name is required (used as project name)</p>
        <div class="flex gap-3">
          <input
            v-model="newSessionName"
            @keydown.enter="handleCreateSession"
            placeholder="Session name (required)"
            required
            class="flex-1 px-3 py-2 bg-background-dark rounded border border-surface-dark focus:outline-none focus:ring-2 focus:ring-accent text-text-inverse"
          />
          <button
            @click="handleCreateSession"
            :disabled="isCreating || !newSessionName.trim()"
            class="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed rounded font-medium transition-colors"
          >
            {{ isCreating ? 'Creating...' : 'Create' }}
          </button>
        </div>
      </div>

      <!-- Existing Sessions -->
      <div class="flex-1 overflow-y-auto custom-scrollbar">
        <h3 class="text-lg font-medium text-text-inverse mb-3">Existing Sessions</h3>
        <div v-if="isLoading" class="text-center py-8 text-text-muted">
          Loading sessions...
        </div>
        <div v-else-if="sessions.length === 0" class="text-center py-8 text-text-muted">
          No sessions found
        </div>
        <div v-else class="space-y-2">
          <button
            v-for="session in sessions"
            :key="session.id"
            @click="handleSelectSession(session)"
            class="w-full text-left p-4 bg-surface-dark rounded-lg hover:bg-surface-dark/80 transition-colors border border-surface-dark hover:border-accent"
          >
            <div class="flex items-center justify-between">
              <div class="flex-1">
                <div class="text-lg font-semibold text-cyan-400">{{ session.title || 'Untitled Session' }}</div>
                <div class="text-sm text-text-muted mt-1">
                  {{ formatDate(session.time?.updated || session.time?.created) }}
                </div>
              </div>
              <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApiClient } from '../composables/useApiClient'

const props = defineProps({
  canClose: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['select', 'create', 'close'])

const { listSessions, createSession } = useApiClient()

const sessions = ref([])
const isLoading = ref(true)
const newSessionName = ref('')
const isCreating = ref(false)

const handleClose = () => {
  if (props.canClose) {
    emit('close')
  }
}

const formatDate = (timestamp) => {
  if (!timestamp) return 'Unknown'
  const date = new Date(timestamp)
  return date.toLocaleString()
}

const loadSessions = async () => {
  isLoading.value = true
  try {
    sessions.value = await listSessions({ limit: 50 })
  } catch (error) {
    console.error('Failed to load sessions:', error)
  } finally {
    isLoading.value = false
  }
}

const handleSelectSession = (session) => {
  emit('select', session.id)
}

const handleCreateSession = async () => {
  if (isCreating.value) return
  
  const sessionName = newSessionName.value.trim()
  if (!sessionName) {
    alert('Please enter a session name')
    return
  }
  
  isCreating.value = true
  try {
    // Use session name as both workspace_name and title
    const session = await createSession(sessionName, sessionName)
    // Ensure title is set (fallback if server doesn't return it)
    session.title = session.title || sessionName
    emit('create', { session, sessionName })
    newSessionName.value = ''
  } catch (error) {
    console.error('Failed to create session:', error)
    alert('Failed to create session: ' + error.message)
  } finally {
    isCreating.value = false
  }
}

onMounted(() => {
  loadSessions()
})
</script>
