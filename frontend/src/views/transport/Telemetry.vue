<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { transportApi } from '@/api'
import { putEvent, listPending, attachAutoSync, removeEvent, markEvent } from '@/offline/idb'
import { syncApi } from '@/api'

const pending = ref<any[]>([])
const online = ref(navigator.onLine)
window.addEventListener('online', () => (online.value = true))
window.addEventListener('offline', () => (online.value = false))

const form = reactive({
  component_id: 1,
  transport_record_id: 1,
  reported_at: new Date().toISOString().slice(0, 16),
  longitude: 119.5,
  latitude: 30.0,
  temperature: 25,
  humidity: 60,
  status: '运输中',
})

async function refresh() {
  pending.value = await listPending()
}

async function submit() {
  const evt = {
    client_id: 'FIELD-SCANNER-01',
    event_type: 'telemetry',
    payload: {
      component_id: form.component_id,
      transport_record_id: form.transport_record_id,
      reported_at: new Date(form.reported_at).toISOString(),
      longitude: form.longitude,
      latitude: form.latitude,
      temperature: form.temperature,
      humidity: form.humidity,
      status: form.status,
    },
    occurred_at: new Date().toISOString(),
    sync_state: 'pending' as const,
  }
  if (!online.value) {
    await putEvent(evt)
    ElMessage.warning('当前离线，已暂存本地，恢复网络后自动同步')
  } else {
    try {
      await transportApi.uploadTelemetry(evt.payload)
      ElMessage.success('轨迹上传成功')
    } catch {
      await putEvent(evt)
      ElMessage.warning('上传失败，已暂存本地')
    }
  }
  await refresh()
}

async function syncNow() {
  const items = await listPending()
  if (!items.length) {
    ElMessage.info('无待同步数据')
    return
  }
  for (const e of items) {
    await markEvent(e.id!, 'syncing')
    try {
      if (e.event_type === 'telemetry') {
        await transportApi.uploadTelemetry(e.payload)
      } else {
        await syncApi.batch({
          client_id: e.client_id,
          batch_id: `manual-${Date.now()}`,
          items: [
            {
              event_type: e.event_type,
              payload: e.payload,
              occurred_at: e.occurred_at,
              client_id: e.client_id,
            },
          ],
        })
      }
      await removeEvent(e.id!)
    } catch (err) {
      await markEvent(e.id!, 'failed', String(err))
    }
  }
  await refresh()
  ElMessage.success('同步完成')
}

attachAutoSync(syncNow)
onMounted(refresh)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>运输车辆轨迹上报</h3>
      <p style="color:#909399; font-size:13px; margin-top:4px;">
        车载终端回传车辆位置与车厢温湿度，平台对偏离路线、超时停留、温湿度越界等异常事件自动生成告警。弱网环境下暂存本地，恢复网络后批量同步。
      </p>
      <el-alert :type="online ? 'success' : 'warning'" :title="online ? '网络正常' : '当前离线，将暂存到 IndexedDB'" show-icon :closable="false" style="margin:8px 0;" />
      <el-form label-width="120px" :model="form" style="max-width:760px;">
        <el-form-item label="构件 ID"><el-input-number v-model="form.component_id" :min="1" /></el-form-item>
        <el-form-item label="出厂记录 ID"><el-input-number v-model="form.transport_record_id" :min="1" /></el-form-item>
        <el-form-item label="上报时间"><el-input v-model="form.reported_at" type="datetime-local" /></el-form-item>
        <el-form-item label="经度"><el-input-number v-model="form.longitude" :precision="6" :step="0.0001" /></el-form-item>
        <el-form-item label="纬度"><el-input-number v-model="form.latitude" :precision="6" :step="0.0001" /></el-form-item>
        <el-form-item label="温度(℃)"><el-input-number v-model="form.temperature" :precision="1" :step="0.5" /></el-form-item>
        <el-form-item label="湿度(%RH)"><el-input-number v-model="form.humidity" :precision="1" :step="0.5" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="已装车" value="已装车" />
            <el-option label="运输中" value="运输中" />
            <el-option label="已到达" value="已到达" />
            <el-option label="已卸货" value="已卸货" />
            <el-option label="偏离路线" value="偏离路线" />
            <el-option label="超时停留" value="超时停留" />
            <el-option label="温湿度越界" value="温湿度越界" />
          </el-select>
        </el-form-item>
        <el-button type="primary" @click="submit">上报</el-button>
        <el-button @click="syncNow">立即同步</el-button>
      </el-form>
    </div>

    <div class="card-section">
      <h3>本地待同步事件（{{ pending.length }}）</h3>
      <el-table :data="pending" border>
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="event_type" label="类型" width="100" />
        <el-table-column label="内容">
          <template #default="{ row }">
            <code style="font-size:12px;">{{ JSON.stringify(row.payload) }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="sync_state" label="状态" width="100" />
        <el-table-column prop="occurred_at" label="发生时间" width="180" />
      </el-table>
    </div>
  </div>
</template>
