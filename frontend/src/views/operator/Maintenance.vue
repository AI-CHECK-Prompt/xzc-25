<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, maintenanceApi } from '@/api'

const checks = ref<any[]>([])
const archivedComponents = ref<any[]>([])
const adviceMap = ref<Record<number, any>>({})

const form = reactive({
  component_id: undefined as number | undefined,
  checked_at: new Date().toISOString().slice(0, 16),
  finding: '正常',
  description: '',
  action_taken: '',
  next_check_in_days: 0,
})

async function load() {
  checks.value = (await maintenanceApi.listChecks()).data
  const all = (await componentApi.list()).data
  archivedComponents.value = all.filter((c: any) => c.current_stage === '已归档')
  for (const c of archivedComponents.value) {
    try {
      const r = (await maintenanceApi.getAdvice(c.id)).data
      adviceMap.value[c.id] = r
    } catch { /* ignore */ }
  }
}

async function submit() {
  if (!form.component_id) {
    ElMessage.warning('请选择构件')
    return
  }
  await maintenanceApi.createCheck({
    ...form,
    checked_at: new Date(form.checked_at).toISOString(),
  })
  ElMessage.success('维护检查记录已登记')
  form.description = ''
  form.action_taken = ''
  await load()
}

function riskType(risk: string) {
  return { low: 'success', medium: 'warning', high: 'danger' }[risk] || 'info'
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>构件维护管理（运营期）</h3>
      <p style="color:#909399; font-size:13px;">
        构件完成档案归档后进入运营期。运营方登记每次维护检查，平台根据构件规格、施工部位、维护历史
        自动输出维护周期建议。下次检查时间 / 风险等级随维护记录持续调整。
      </p>
    </div>

    <div class="card-section">
      <h3>① 登记维护检查</h3>
      <el-form label-width="120px" :model="form" style="max-width:760px;">
        <el-form-item label="已归档构件" required>
          <el-select v-model="form.component_id" filterable style="width:100%;">
            <el-option
              v-for="c in archivedComponents"
              :key="c.id"
              :value="c.id"
              :label="`${c.trace_code} (${c.spec})`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="检查时间">
          <el-input v-model="form.checked_at" type="datetime-local" />
        </el-form-item>
        <el-form-item label="检查发现">
          <el-radio-group v-model="form.finding">
            <el-radio-button value="正常">正常</el-radio-button>
            <el-radio-button value="轻微异常">轻微异常</el-radio-button>
            <el-radio-button value="严重异常">严重异常</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="问题描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="处理措施">
          <el-input v-model="form.action_taken" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="下次检查(天)">
          <el-input-number v-model="form.next_check_in_days" :min="0" :max="3650" />
          <span style="margin-left:8px; color:#909399; font-size:12px;">
            0 = 平台按规则自动建议
          </span>
        </el-form-item>
        <el-button type="primary" @click="submit">登记</el-button>
      </el-form>
    </div>

    <div class="card-section">
      <h3>② 维护周期建议</h3>
      <el-table :data="archivedComponents" border>
        <el-table-column prop="trace_code" label="追溯码" width="220" />
        <el-table-column prop="spec" label="规格" />
        <el-table-column prop="component_type" label="类型" width="120" />
        <el-table-column label="最近一次" width="120">
          <template #default="{ row }">
            <el-tag v-if="adviceMap[row.id]?.current_finding" size="small">
              {{ adviceMap[row.id].current_finding }}
            </el-tag>
            <span v-else style="color:#909399;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="建议周期" width="100">
          <template #default="{ row }">
            {{ adviceMap[row.id]?.suggested_cycle_days ?? '—' }} 天
          </template>
        </el-table-column>
        <el-table-column label="下次检查" width="180">
          <template #default="{ row }">
            {{ adviceMap[row.id]?.next_check_at ?? '—' }}
          </template>
        </el-table-column>
        <el-table-column label="风险" width="100">
          <template #default="{ row }">
            <el-tag v-if="adviceMap[row.id]" :type="riskType(adviceMap[row.id].risk_level)">
              {{ adviceMap[row.id].risk_level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="建议依据" show-overflow-tooltip>
          <template #default="{ row }">
            {{ adviceMap[row.id]?.rationale ?? '—' }}
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card-section">
      <h3>③ 维护检查历史</h3>
      <el-table :data="checks" border>
        <el-table-column prop="component_id" label="构件 ID" width="100" />
        <el-table-column prop="checked_at" label="检查时间" width="180" />
        <el-table-column prop="finding" label="发现" width="120" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column prop="action_taken" label="处理" show-overflow-tooltip />
        <el-table-column label="下次检查" width="120">
          <template #default="{ row }">
            {{ row.next_check_in_days ? row.next_check_in_days + ' 天' : '平台建议' }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
