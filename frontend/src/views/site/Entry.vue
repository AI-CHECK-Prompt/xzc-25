<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, siteApi } from '@/api'

const components = ref<any[]>([])
const form = reactive({
  component_id: undefined as number | undefined,
  entered_at: new Date().toISOString().slice(0, 16),
  stack_location: '',
  inspector: '',
  acceptance: '合格',
  remark: '',
})

async function load() {
  // 仅显示未进场或可补录的构件
  components.value = (await componentApi.list()).data.filter(
    (c: any) => c.current_stage === '已到场' || c.current_stage === '运输中' || c.current_stage === '已生产',
  )
}

async function submit() {
  if (!form.component_id) {
    ElMessage.warning('请选择构件')
    return
  }
  await siteApi.entry({ ...form, entered_at: new Date(form.entered_at).toISOString() })
  ElMessage.success('进场登记成功')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="card-section">
    <h3>构件进场登记</h3>
    <p style="color:#909399; font-size:13px;">
      工地入口扫码终端读取构件追溯码，登记进场时间、堆放位置、现场验收结论。
      <el-tag type="danger" size="small">验收结论为不合格的构件禁止进入吊装流程</el-tag>
    </p>
    <el-form label-width="120px" :model="form" style="max-width:760px;">
      <el-form-item label="构件追溯码" required>
        <el-select v-model="form.component_id" filterable placeholder="选择构件" style="width:100%;">
          <el-option v-for="c in components" :key="c.id" :value="c.id" :label="`${c.trace_code} (${c.spec})`" />
        </el-select>
      </el-form-item>
      <el-form-item label="进场时间"><el-input v-model="form.entered_at" type="datetime-local" /></el-form-item>
      <el-form-item label="堆放位置"><el-input v-model="form.stack_location" placeholder="例如 A区堆场B3-12" /></el-form-item>
      <el-form-item label="验收人"><el-input v-model="form.inspector" /></el-form-item>
      <el-form-item label="验收结论">
        <el-radio-group v-model="form.acceptance">
          <el-radio-button value="合格">合格</el-radio-button>
          <el-radio-button value="不合格">不合格</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      <el-button type="primary" @click="submit">提交进场登记</el-button>
    </el-form>
  </div>
</template>
