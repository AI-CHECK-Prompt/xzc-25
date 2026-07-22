<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { archiveApi, transportApi } from '@/api'

const alerts = ref<any[]>([])
const archives = ref<any[]>([])

async function load() {
  alerts.value = (await transportApi.alerts()).data
  archives.value = (await archiveApi.list()).data
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>监督抽检告警</h3>
      <el-table :data="alerts" border>
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="component_id" label="构件 ID" width="100" />
        <el-table-column prop="alert_type" label="类型" width="120" />
        <el-table-column prop="detail" label="详情" />
        <el-table-column prop="created_at" label="时间" width="200" />
      </el-table>
    </div>
    <div class="card-section">
      <h3>已报送档案（待签收）</h3>
      <el-table :data="archives" border>
        <el-table-column prop="archive_no" label="档案号" width="220" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="submitted_at" label="报送时间" width="200" />
      </el-table>
    </div>
  </div>
</template>
