<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, siteApi } from '@/api'

const components = ref<any[]>([])
const form = reactive({
  trace_code: '',
  accepted_at: new Date().toISOString().slice(0, 16),
  quality_grade: '合格',
  inspector: '',
  conclusion: '',
})

async function load() {
  components.value = (await componentApi.list()).data.filter(
    (c: any) => c.current_stage === '节点连接' || c.current_stage === '已隐蔽',
  )
}

async function submit() {
  const comp = components.value.find((c: any) => c.trace_code === form.trace_code)
  if (!comp) {
    ElMessage.warning('请选择已节点连接的构件')
    return
  }
  await siteApi.concealed({
    component_id: comp.id,
    accepted_at: new Date(form.accepted_at).toISOString(),
    quality_grade: form.quality_grade,
    inspector: form.inspector,
    conclusion: form.conclusion,
  })
  ElMessage.success('隐蔽工程验收完成')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="card-section">
    <h3>隐蔽工程验收</h3>
    <p style="color:#909399; font-size:13px;">监理单位扫码确认连接质量、上传隐蔽验收影像。</p>
    <el-form label-width="120px" :model="form" style="max-width:760px;">
      <el-form-item label="构件追溯码" required>
        <el-select v-model="form.trace_code" filterable>
          <el-option v-for="c in components" :key="c.trace_code" :value="c.trace_code" :label="`${c.trace_code} (${c.spec})`" />
        </el-select>
      </el-form-item>
      <el-form-item label="验收时间"><el-input v-model="form.accepted_at" type="datetime-local" /></el-form-item>
      <el-form-item label="质量等级">
        <el-radio-group v-model="form.quality_grade">
          <el-radio-button value="合格">合格</el-radio-button>
          <el-radio-button value="优良">优良</el-radio-button>
          <el-radio-button value="不合格">不合格</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="监理员"><el-input v-model="form.inspector" /></el-form-item>
      <el-form-item label="结论说明"><el-input v-model="form.conclusion" type="textarea" :rows="2" /></el-form-item>
      <el-button type="primary" @click="submit">提交验收</el-button>
    </el-form>
  </div>
</template>
