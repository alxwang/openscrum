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
          <div
            v-for="session in sessions"
            :key="session.id"
            @click="handleSelectSession(session)"
            class="w-full text-left p-4 bg-surface-dark rounded-lg hover:bg-surface-dark/80 transition-colors border border-surface-dark hover:border-accent cursor-pointer"
          >
            <div class="flex items-center justify-between">
              <div class="flex-1">
                <div class="text-lg font-semibold text-cyan-400">{{ session.title || 'Untitled Session' }}</div>
                <div class="text-sm text-text-muted mt-1">
                  {{ formatDate(session.time?.updated || session.time?.created) }}
                </div>
              </div>
              <div class="flex items-center space-x-2">
                <button 
                  @click.stop="handleDeleteSession(session)"
                  :disabled="isDeleting === session.id"
                  class="p-2 text-text-muted hover:text-red-400 hover:bg-red-400/10 rounded transition-colors"
                  title="Delete Session"
                >
                  <svg v-if="isDeleting === session.id" class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <svg v-else xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
                  </svg>
                </button>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Confirm Delete Modal -->
    <div v-if="sessionToDelete" class="fixed inset-0 bg-black/80 flex items-center justify-center z-[60]" @click.self="!isDeleting && (sessionToDelete = null)">
      <div class="bg-surface-dark border border-red-500/50 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
        <div class="flex items-center gap-3 text-red-400 mb-4">
          <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <h3 class="text-xl font-bold">Delete Session?</h3>
        </div>
        <p class="text-text-regular mb-6">
          Are you sure you want to completely delete <strong>{{ sessionToDelete.title || sessionToDelete.id }}</strong>?
          <br><br>
          This will permanently destroy the API records, LLM conversation memory log, and the physical workspace directory containing all traced code.
        </p>
        <div class="flex justify-end gap-3">
          <button @click="sessionToDelete = null" :disabled="isDeleting" class="px-4 py-2 bg-surface text-text-inverse rounded hover:bg-surface-light transition-colors">
            Cancel
          </button>
          <button @click="confirmDelete" :disabled="isDeleting" class="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded font-medium transition-colors">
            {{ isDeleting ? 'Deleting...' : 'Permanently Delete' }}
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

const emit = defineEmits(['select', 'create', 'close', 'delete'])

const { listSessions, createSession, deleteSession } = useApiClient()

const sessions = ref([])
const isLoading = ref(true)
const newSessionName = ref('')
const isCreating = ref(false)
const isDeleting = ref(null)
const sessionToDelete = ref(null)

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

const handleDeleteSession = (session) => {
  if (isDeleting.value) return
  sessionToDelete.value = session
}

const confirmDelete = async () => {
  if (!sessionToDelete.value || isDeleting.value) return

  const session = sessionToDelete.value
  isDeleting.value = session.id
  try {
    await deleteSession(session.id)
    // Remove from local list
    sessions.value = sessions.value.filter(s => s.id !== session.id)
    // Inform parent component it was deleted in case it requires reset
    emit('delete', session.id)
    sessionToDelete.value = null
  } catch (error) {
    console.error('Failed to delete session:', error)
    alert('Failed to delete session: ' + error.message)
  } finally {
    isDeleting.value = null
  }
}

onMounted(() => {
  loadSessions()
})
</script>
