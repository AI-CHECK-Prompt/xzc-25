<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, siteApi } from '@/api'

const components = ref<any[]>([])
const form = reactive({
  trace_code: '',
  decoration: '',
  mep: '',
  measures: '已贴保护膜',
})

async function load() {
  components.value = (await componentApi.list()).data.filter(
    (c: any) => c.current_stage === '已隐蔽' || c.current_stage === '成品保护',
  )
}

async function submit() {
  const comp = components.value.find((c: any) => c.trace_code === form.trace_code)
  if (!comp) {
    ElMessage.warning('请选择已隐蔽验收的构件')
    return
  }
  await siteApi.protection({
    component_id: comp.id,
    decoration: form.decoration,
    mep: form.mep,
    measures: form.measures,
  })
  ElMessage.success('成品保护登记成功')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="card-section">
    <h3>成品保护登记</h3>
    <p style="color:#909399; font-size:13px;">
      记录后续装饰、机电安装、成品保护措施。机电动火作业未配套防火保护时，系统自动提示作业班组。
    </p>
    <el-form label-width="120px" :model="form" style="max-width:760px;">
      <el-form-item label="构件追溯码" required>
        <el-select v-model="form.trace_code" filterable>
          <el-option v-for="c in components" :key="c.trace_code" :value="c.trace_code" :label="`${c.trace_code} (${c.spec})`" />
        </el-select>
      </el-form-item>
      <el-form-item label="装饰"><el-input v-model="form.decoration" placeholder="如 内墙抹灰 / 精装 / 待装饰" /></el-form-item>
      <el-form-item label="机电"><el-input v-model="form.mep" placeholder="如 电管预埋 / 电焊切割 / 通风安装" /></el-form-item>
      <el-form-item label="保护措施"><el-input v-model="form.measures" type="textarea" :rows="2" /></el-form-item>
      <el-button type="primary" @click="submit">提交</el-button>
    </el-form>
  </div>
</template>
