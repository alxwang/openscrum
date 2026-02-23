<template>
  <div class="file-tree-node select-none py-0.5">
    <!-- Node item -->
    <div 
      class="flex items-center gap-2 py-1.5 px-2 rounded-lg transition-colors cursor-pointer group"
      :class="[
        node.type === 'file' && node.path === selectedFile 
          ? 'bg-accent text-text-inverse' 
          : 'hover:bg-surface text-text'
      ]"
      @click="toggle"
    >
      <!-- Indent -->
      <div v-if="!isRoot" class="flex" :style="{ width: `${depth * 12}px` }"></div>
      
      <!-- Icon/Caret -->
      <div 
        class="w-4 h-4 flex items-center justify-center transition-colors"
        :class="node.type === 'file' && node.path === selectedFile ? 'text-text-inverse opacity-80' : 'text-text-muted group-hover:text-surface-dark'"
      >
        <template v-if="node.type === 'directory'">
          <svg v-if="isOpen" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
            <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 -rotate-90">
            <path fill-rule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
          </svg>
        </template>
        <template v-else>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 opacity-60">
            <path fill-rule="evenodd" d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Zm2.25 8.5a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Zm0 3a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Z" clip-rule="evenodd" />
          </svg>
        </template>
      </div>

      <!-- Colored Folder Icon -->
      <div v-if="node.type === 'directory'" class="text-accent flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path d="M3.75 3A1.75 1.75 0 0 0 2 4.75v3.26a3.235 3.235 0 0 1 1.25-.26h13.5c.444 0 .869.095 1.25.26V6.75A1.75 1.75 0 0 0 16.25 5h-4.836a.25.25 0 0 1-.177-.073L9.823 3.513A1.75 1.75 0 0 0 8.586 3H3.75ZM3.75 9A1.75 1.75 0 0 0 2 10.75v4.5c0 .966.784 1.75 1.75 1.75h12.5A1.75 1.75 0 0 0 18 15.25v-4.5A1.75 1.75 0 0 0 16.25 9H3.75Z" />
        </svg>
      </div>
      
      <!-- Label -->
      <span 
        class="truncate transition-colors" 
        :class="[
          node.type === 'directory' ? 'text-text-inverse font-medium group-hover:text-surface-dark' : '',
          node.type === 'file' && node.path === selectedFile
            ? 'text-text-inverse font-medium'
            : (node.type === 'directory' ? '' : 'text-text-inverse group-hover:text-surface-dark font-medium')
        ]"
      >
        {{ displayName }}
      </span>
    </div>

    <!-- Children (Recursive) -->
    <div v-if="isOpen && node.type === 'directory' && node.children?.length > 0">
      <FileTreeNode 
        v-for="(child, index) in node.children" 
        :key="`${child.name}-${index}`" 
        :node="child" 
        :depth="depth + 1" 
        :selectedFile="selectedFile"
        @select-file="$emit('select-file', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  depth: {
    type: Number,
    default: 0
  },
  isRoot: {
    type: Boolean,
    default: false
  },
  selectedFile: {
    type: String,
    default: null
  }
})

const emit = defineEmits(['select-file'])

// Default open for root and top-level directories
const isOpen = ref(props.isRoot || props.depth < 1)

const toggle = () => {
  if (props.node.type === 'directory') {
    isOpen.value = !isOpen.value
  } else if (props.node.type === 'file' && props.node.path) {
    emit('select-file', props.node.path)
  }
}

const displayName = computed(() => {
  // Give the root node a nicer name for display
  if (props.isRoot) {
    return 'Workspace Root'
  }
  return props.node.name
})
</script>
