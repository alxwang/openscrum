<template>
  <div class="file-tree font-mono text-sm h-full w-full">
    <div v-if="loading" class="p-4 text-text-muted flex items-center justify-center h-full">
      <div class="animate-pulse">Loading workspace...</div>
    </div>
    <div v-else-if="error" class="p-4 text-red-500">
      {{ error }}
    </div>
    <div v-else class="h-full overflow-y-auto custom-scrollbar p-2">
      <!-- Root directory always open -->
      <FileTreeNode 
        :node="tree" 
        :isRoot="true" 
        :selectedFile="selectedFile"
        @select-file="$emit('select-file', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useApiClient } from '../composables/useApiClient'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps({
  sessionId: {
    type: String,
    required: true
  },
  refreshTrigger: {
    type: Number,
    default: 0
  },
  selectedFile: {
    type: String,
    default: null
  }
})

defineEmits(['select-file'])

const { fetchWorkspaceTree } = useApiClient()
const tree = ref({ name: 'root', type: 'directory', children: [] })
const loading = ref(true)
const error = ref(null)

const loadTree = async () => {
  if (!props.sessionId) return
  try {
    loading.value = true
    error.value = null
    tree.value = await fetchWorkspaceTree(props.sessionId)
  } catch (err) {
    console.error('Failed to load file tree:', err)
    error.value = 'Failed to load workspace files.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadTree()
})

watch(() => props.sessionId, () => {
  loadTree()
})

watch(() => props.refreshTrigger, () => {
  if (props.sessionId) {
    loadTree()
  }
})
</script>
