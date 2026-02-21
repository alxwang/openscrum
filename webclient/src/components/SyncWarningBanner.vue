<template>
  <div v-if="warnings.length > 0" class="sync-warning-banner" :class="{ 'expanded': isExpanded }">
    <div class="banner-header" @click="toggleExpand">
      <div class="banner-title">
        <span class="warning-icon">⚠️</span>
        <span class="warning-text">
          Codebase is out of sync with Design Documents ({{ warnings.length }} warning{{ warnings.length > 1 ? 's' : '' }})
        </span>
      </div>
      <div class="banner-actions">
        <button v-if="!isExpanded" class="btn-sm btn-outline" @click.stop="toggleExpand">View details</button>
        <button class="btn-sm btn-primary" @click.stop="onSync" :disabled="isSyncing">
          {{ isSyncing ? 'Syncing...' : 'Sync Design from Code' }}
        </button>
      </div>
    </div>
    
    <div v-if="isExpanded" class="banner-content">
      <ul class="warning-list">
        <li v-for="(warning, index) in warnings" :key="index" class="warning-item">
          <span class="severity-bullet" :class="warning.severity"></span>
          <span class="warning-message">{{ warning.message }}</span>
        </li>
      </ul>
      <p class="sync-explanation">
        Running a sync will reverse-engineer your current codebase and update the design documents to match. This process may overwrite existing documentation if the code has drifted significantly.
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  warnings: {
    type: Array,
    default: () => []
  },
  isSyncing: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['trigger-sync'])

const isExpanded = ref(false)

const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
}

const onSync = () => {
  emit('trigger-sync')
}
</script>

<style scoped>
.sync-warning-banner {
  margin: 1rem 0;
  border-radius: var(--radius-md, 6px);
  background-color: var(--warning-bg, #fff8e6);
  border: 1px solid var(--warning-border, #ffc107);
  overflow: hidden;
  transition: all 0.2s ease;
}

.banner-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  cursor: pointer;
  gap: 1rem;
  flex-wrap: wrap;
}

.banner-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
  color: var(--warning-text, #856404);
}

.warning-icon {
  font-size: 1.1rem;
}

.banner-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.875rem;
  border-radius: var(--radius-sm, 4px);
  cursor: pointer;
  border: none;
  font-weight: 500;
}

.btn-outline {
  background: transparent;
  border: 1px solid var(--warning-text, #856404);
  color: var(--warning-text, #856404);
}

.btn-primary {
  background-color: var(--warning-text, #856404);
  color: white;
}

.btn-primary:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.banner-content {
  padding: 0 1rem 1rem;
  border-top: 1px dashed var(--warning-border, #ffc107);
  margin-top: 0.25rem;
  padding-top: 0.75rem;
}

.warning-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.warning-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  color: var(--text-color, #333);
}

.severity-bullet {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}

.severity-bullet.warning {
  background-color: #ff9800;
}

.severity-bullet.critical {
  background-color: #f44336;
}

.severity-bullet.info {
  background-color: #2196f3;
}

.sync-explanation {
  font-size: 0.85rem;
  color: var(--text-muted, #666);
  margin-top: 1rem;
  margin-bottom: 0;
  font-style: italic;
}
</style>
