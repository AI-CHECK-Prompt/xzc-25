<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { qualityApi } from '@/api'

const tasks = ref<any[]>([])
const selected = ref<number | null>(null)

const form = reactive({
  inspected_at: new Date().toISOString().slice(0, 16),
  location: '',
  conclusion: '合格',
  findings: '',
  measures: '',
  is_reinspection: false,
})

async function load() {
  tasks.value = (await qualityApi.listTasks({ only_open: true })).data
}

async function submit() {
  if (!selected.value) {
    ElMessage.warning('请选择抽检任务')
    return
  }
  await qualityApi.submitRecord({
    task_id: selected.value,
    inspected_at: new Date(form.inspected_at).toISOString(),
    location: form.location,
    conclusion: form.conclusion,
    findings: form.findings,
    measures: form.measures,
    is_reinspection: form.is_reinspection,
  })
  if (form.conclusion === '不合格') {
    ElMessage.warning('抽检不合格已实时回传，平台已自动开整改并阻断下游工序')
  } else if (form.is_reinspection) {
    ElMessage.success('复核结果已回传，平台已解除阻断')
  } else {
    ElMessage.success('抽检记录已实时回传平台')
  }
  form.findings = ''
  form.measures = ''
  form.location = ''
  await load()
}

onMounted(load)
</script>

<template>
  <div style="max-width:680px; margin:0 auto;">
    <div class="card-section" style="background:linear-gradient(135deg,#1d4ed8,#06b6d4); color:#fff;">
      <h3 style="color:#fff; margin:0;">📱 质监现场抽检录入</h3>
      <p style="color:#cbd5e1; font-size:13px; margin:8px 0 0;">
        移动端友好：现场扫码选择任务 → 录入抽检记录 → 实时回传平台。
        抽检结论为不合格时，平台自动开整改并阻断该构件下游工序。
      </p>
    </div>

    <div class="card-section">
      <h3>① 选择抽检任务</h3>
      <el-select v-model="selected" placeholder="选择未闭环任务" filterable style="width:100%;">
        <el-option
          v-for="t in tasks"
          :key="t.id"
          :value="t.id"
          :label="`${t.task_no} | 工序：${t.stage} | ${t.title || '—'}`"
        />
      </el-select>
    </div>

    <div class="card-section">
      <h3>② 录入抽检结果</h3>
      <el-form label-width="100px" :model="form">
        <el-form-item label="抽检时间">
          <el-input v-model="form.inspected_at" type="datetime-local" />
        </el-form-item>
        <el-form-item label="抽检地点">
          <el-input v-model="form.location" placeholder="如：A 区 3F 屋面节点" />
        </el-form-item>
        <el-form-item label="抽检结论">
          <el-radio-group v-model="form.conclusion">
            <el-radio-button value="合格">合格</el-radio-button>
            <el-radio-button value="不合格">不合格</el-radio-button>
            <el-radio-button value="整改后合格">整改后合格</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="是否复核">
          <el-switch v-model="form.is_reinspection"
            active-text="是（必须由原抽检人提交）" />
        </el-form-item>
        <el-form-item label="问题描述">
          <el-input v-model="form.findings" type="textarea" :rows="3"
            placeholder="外观 / 尺寸 / 强度 / 防水 / 连接 描述" />
        </el-form-item>
        <el-form-item label="处置措施">
          <el-input v-model="form.measures" type="textarea" :rows="2"
            placeholder="建议：返工 / 修补 / 重新灌浆 / 加强检测 等" />
        </el-form-item>
        <el-button type="primary" size="large" @click="submit" style="width:100%;">
          实时回传平台
        </el-button>
      </el-form>
    </div>
  </div>
</template>
