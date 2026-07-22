<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { transportApi } from '@/api'

const alerts = ref<any[]>([])

async function load() {
  alerts.value = (await transportApi.alerts()).data
}

onMounted(load)
</script>

<template>
  <div class="card-section">
    <h3>运输异常告警</h3>
    <p style="color:#909399; font-size:13px;">偏离路线、超时停留、温湿度越界自动触发。</p>
    <el-table :data="alerts" border>
      <el-table-column prop="id" label="#" width="60" />
      <el-table-column prop="component_id" label="构件 ID" width="100" />
      <el-table-column prop="alert_type" label="告警类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.alert_type === 'TEMP_OUT' ? 'danger' : 'warning'">
            {{ row.alert_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="detail" label="详情" />
      <el-table-column prop="resolved" label="已处理" width="100">
        <template #default="{ row }">
          <el-tag :type="row.resolved ? 'success' : 'info'">{{ row.resolved ? '是' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="200" />
    </el-table>
  </div>
</template>
