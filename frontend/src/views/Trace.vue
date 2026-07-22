<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { traceApi } from '@/api'

const route = useRoute()
const code = ref<string>((route.params.code as string) || (route.query.code as string) || '')
const data = ref<any>(null)
const qrImage = ref<string>('')

// 告警类型 → 显示名称/颜色，与 transport/Alerts.vue 保持一致
const ALERT_LABELS: Record<string, { label: string; type: 'danger' | 'warning' | 'info' }> = {
  TEMP_OUT: { label: '温度越界', type: 'danger' },
  OFF_ROUTE: { label: '偏离路线', type: 'warning' },
  OVERSTAY: { label: '超时停留', type: 'warning' },
}

function alertStyle(alertType: string) {
  return ALERT_LABELS[alertType] || { label: alertType, type: 'info' as const }
}

function timelineAlerts(t: any) {
  // 仅当 extras 里携带 alerts 列表时返回；保持向后兼容（无该字段时退化为空）
  if (!t || !t.extras || !Array.isArray(t.extras.alerts)) return []
  return t.extras.alerts
}

async function load() {
  if (!code.value) return
  try {
    data.value = (await traceApi.get(code.value)).data
    qrImage.value = await QRCode.toDataURL(location.href, { width: 120 })
  } catch (e) {
    ElMessage.error('未找到该追溯码')
  }
}

async function search() {
  await load()
}

watch(() => route.params.code, (v) => {
  if (v) {
    code.value = v as string
    load()
  }
})

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>构件追溯查询</h3>
      <p style="color:#909399; font-size:13px;">输入唯一追溯码或扫描二维码，查看从生产到档案归档的全链路记录。</p>
      <div style="display:flex; gap:8px; align-items:center; max-width:600px;">
        <el-input v-model="code" placeholder="例如 PC-20250722-FACTORY01-0001" @keyup.enter="search" />
        <el-button type="primary" @click="search">查询</el-button>
        <img v-if="qrImage" :src="qrImage" alt="qr" style="width:60px; height:60px;" />
      </div>
    </div>

    <div v-if="data" class="card-section">
      <h3>{{ data.component.trace_code }} ｜ {{ data.component.component_type }} ｜ {{ data.component.spec }}</h3>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="模具编号">{{ data.component.mould_no }}</el-descriptions-item>
        <el-descriptions-item label="钢筋批号">{{ data.component.rebar_batch }}</el-descriptions-item>
        <el-descriptions-item label="配合比">{{ data.component.concrete_ratio }}</el-descriptions-item>
        <el-descriptions-item label="浇筑时间">{{ data.component.pour_at }}</el-descriptions-item>
        <el-descriptions-item label="强度报告">{{ data.component.strength_report }}</el-descriptions-item>
        <el-descriptions-item label="出厂自检">{{ data.component.factory_inspection }}</el-descriptions-item>
        <el-descriptions-item label="RFID 标签">{{ data.component.rfid_tag }}</el-descriptions-item>
        <el-descriptions-item label="当前阶段">{{ data.component.current_stage }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-if="data" class="card-section">
      <h3>全链路时间线（{{ data.timeline.length }} 步）</h3>
      <div v-for="(t, i) in data.timeline" :key="i" class="timeline-card">
        <div>
          <span class="stage">{{ t.stage }}</span>
          <span class="actor">{{ t.actor }}（{{ t.party_role }}）</span>
          <el-tag style="margin-left:8px;" size="small">{{ t.occurred_at || '—' }}</el-tag>
        </div>
        <div class="summary">{{ t.summary }}</div>
        <!--
          同一遥测点可能同时存在多条不同类型的告警（如温度越界 + 偏离路线）。
          在轨迹卡片下方以独立标签分行展示，不再与 summary 混排，
          运营人员可一眼看清当前是哪种异常在持续。
        -->
        <div v-if="timelineAlerts(t).length" class="alert-list">
          <div v-for="a in timelineAlerts(t)" :key="a.id" class="alert-row">
            <el-tag :type="alertStyle(a.alert_type).type" size="small" effect="dark">
              {{ alertStyle(a.alert_type).label }}
            </el-tag>
            <span class="alert-detail">{{ a.detail }}</span>
            <el-tag v-if="a.resolved" type="success" size="small">已处置</el-tag>
            <el-tag v-else type="info" size="small">未处置</el-tag>
            <span class="alert-time">{{ a.created_at }}</span>
          </div>
        </div>
        <div v-if="t.extras && Object.keys(t.extras).length" style="margin-top:6px; font-size:12px; color:#909399;">
          <code>{{ JSON.stringify(t.extras) }}</code>
        </div>
      </div>
    </div>

    <div v-if="data && data.archives && data.archives.length" class="card-section">
      <h3>电子档案</h3>
      <el-table :data="data.archives" border>
        <el-table-column prop="archive_no" label="档案号" width="220" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="submitted_at" label="报送时间" width="200" />
      </el-table>
    </div>
  </div>
</template>
