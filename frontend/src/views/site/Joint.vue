<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, siteApi } from '@/api'

const components = ref<any[]>([])
const form = reactive({
  trace_code: '',
  grout_at: new Date().toISOString().slice(0, 16),
  grout_batch: '',
  bedding_at: '',
  connection_type: '灌浆套筒',
  operator: '',
})

async function load() {
  components.value = (await componentApi.list()).data.filter(
    (c: any) => c.current_stage === '已吊装' || c.current_stage === '节点连接',
  )
}

async function submit() {
  const comp = components.value.find((c: any) => c.trace_code === form.trace_code)
  if (!comp) {
    ElMessage.warning('请选择已吊装的构件')
    return
  }
  await siteApi.joint({
    component_id: comp.id,
    grout_at: new Date(form.grout_at).toISOString(),
    grout_batch: form.grout_batch,
    bedding_at: form.bedding_at ? new Date(form.bedding_at).toISOString() : null,
    connection_type: form.connection_type,
    operator: form.operator,
  })
  ElMessage.success('节点连接登记成功')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="card-section">
    <h3>节点连接登记（灌浆、座浆等）</h3>
    <el-form label-width="120px" :model="form" style="max-width:760px;">
      <el-form-item label="构件追溯码" required>
        <el-select v-model="form.trace_code" filterable>
          <el-option v-for="c in components" :key="c.trace_code" :value="c.trace_code" :label="`${c.trace_code} (${c.spec})`" />
        </el-select>
      </el-form-item>
      <el-form-item label="灌浆时间"><el-input v-model="form.grout_at" type="datetime-local" /></el-form-item>
      <el-form-item label="灌浆料批号"><el-input v-model="form.grout_batch" /></el-form-item>
      <el-form-item label="座浆时间"><el-input v-model="form.bedding_at" type="datetime-local" /></el-form-item>
      <el-form-item label="连接方式">
        <el-select v-model="form.connection_type">
          <el-option label="灌浆套筒" value="灌浆套筒" />
          <el-option label="灌浆座浆" value="灌浆座浆" />
          <el-option label="后浇连接" value="后浇连接" />
          <el-option label="焊接连接" value="焊接连接" />
          <el-option label="螺栓连接" value="螺栓连接" />
        </el-select>
      </el-form-item>
      <el-form-item label="作业员"><el-input v-model="form.operator" /></el-form-item>
      <el-button type="primary" @click="submit">提交</el-button>
    </el-form>
  </div>
</template>
