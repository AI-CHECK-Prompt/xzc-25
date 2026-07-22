<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { siteApi } from '@/api'

const eligible = ref<any[]>([])
const form = reactive({
  trace_code: '',
  hoisted_at: new Date().toISOString().slice(0, 16),
  equipment_no: '',
  signal_worker: '',
  rigger: '',
  coord_lng: 119.965,
  coord_lat: 30.276,
  result: '一次就位',
})

async function load() {
  eligible.value = (await siteApi.eligible()).data
}

async function submit() {
  if (!form.trace_code) {
    ElMessage.warning('请选择可吊装构件')
    return
  }
  const target = eligible.value.find((c: any) => c.trace_code === form.trace_code)
  if (!target) return
  try {
    await siteApi.hoist({
      component_id: undefined,
      hoisted_at: new Date(form.hoisted_at).toISOString(),
      equipment_no: form.equipment_no,
      signal_worker: form.signal_worker,
      rigger: form.rigger,
      coord_lng: form.coord_lng,
      coord_lat: form.coord_lat,
      result: form.result,
    } as any)
    // 实际上接口需要 component_id
  } catch (e) {
    // 拦截器已处理
  }
  // 通过 trace_code 解析 component id 重试（因为接口需要 component_id）
  // 简化：直接通过 componentApi 列表查找
  await load()
}

async function hoistByCode(code: string) {
  // 真正提交流程：先按 trace_code 查 component_id
  // 这里通过 componentApi 接口列中匹配
  const all = (await import('@/api')).componentApi
  const list = (await all.list()).data
  const comp = list.find((c: any) => c.trace_code === code)
  if (!comp) {
    ElMessage.error('未找到构件')
    return
  }
  try {
    await siteApi.hoist({
      component_id: comp.id,
      hoisted_at: new Date(form.hoisted_at).toISOString(),
      equipment_no: form.equipment_no,
      signal_worker: form.signal_worker,
      rigger: form.rigger,
      coord_lng: form.coord_lng,
      coord_lat: form.coord_lat,
      result: form.result,
    })
    ElMessage.success('吊装登记成功')
    await load()
  } catch {}
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>可吊装构件（自动排除不合格件）</h3>
      <el-alert type="info" :closable="false" show-icon
        title="系统已根据进场验收结论过滤：不合格件不会出现在列表中，且即使手动传入也会被后端拒绝。" />
      <el-table :data="eligible" border style="margin-top:8px;">
        <el-table-column prop="trace_code" label="追溯码" width="220" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="spec" label="规格" />
        <el-table-column prop="current_stage" label="阶段" width="120" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="hoistByCode(row.trace_code)">吊装登记</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card-section">
      <h3>吊装登记表单</h3>
      <el-form label-width="120px" :model="form" style="max-width:760px;">
        <el-form-item label="构件追溯码">
          <el-select v-model="form.trace_code" filterable placeholder="从上方列表选择">
            <el-option v-for="c in eligible" :key="c.trace_code" :value="c.trace_code" :label="c.trace_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="吊装时间"><el-input v-model="form.hoisted_at" type="datetime-local" /></el-form-item>
        <el-form-item label="设备编号"><el-input v-model="form.equipment_no" placeholder="例如 TC7032" /></el-form-item>
        <el-form-item label="信号工"><el-input v-model="form.signal_worker" /></el-form-item>
        <el-form-item label="司索工"><el-input v-model="form.rigger" /></el-form-item>
        <el-form-item label="经度"><el-input-number v-model="form.coord_lng" :precision="6" /></el-form-item>
        <el-form-item label="纬度"><el-input-number v-model="form.coord_lat" :precision="6" /></el-form-item>
        <el-form-item label="结果">
          <el-radio-group v-model="form.result">
            <el-radio-button value="一次就位">一次就位</el-radio-button>
            <el-radio-button value="调整后到位">调整后到位</el-radio-button>
            <el-radio-button value="未到位">未到位</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-button type="primary" @click="hoistByCode(form.trace_code)">提交吊装登记</el-button>
      </el-form>
    </div>
  </div>
</template>
