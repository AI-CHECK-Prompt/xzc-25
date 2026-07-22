<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { componentApi, metaApi } from '@/api'

const projects = ref<any[]>([])
const components = ref<any[]>([])
const form = reactive({
  project_id: undefined as number | undefined,
  component_type: '外墙板',
  spec: '',
  quantity: 1,
  mould_no: '',
  rebar_batch: '',
  concrete_ratio: 'C40',
  pour_at: new Date().toISOString().slice(0, 16),
  curing_record: '标准养护 14 天',
  strength_report: '',
  embedded_parts: { 吊点: 4, 电气盒: 2, 灌浆套筒: 6 },
  factory_inspection: '合格',
})

async function load() {
  projects.value = (await metaApi.projects()).data
  components.value = (await componentApi.list()).data
}

async function submit() {
  if (!form.project_id) {
    ElMessage.warning('请选择项目')
    return
  }
  await componentApi.create({ ...form, pour_at: new Date(form.pour_at).toISOString() })
  ElMessage.success('构件录入成功，已生成唯一追溯码')
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>构件生产录入</h3>
      <p style="color:#909399; font-size:13px; margin-top:4px;">
        工厂端录入每一件构件的模具编号、钢筋原材料批号、混凝土配合比、浇筑时间、养护记录、强度报告、预埋件信息、出厂检验结论，平台自动生成唯一追溯码（兼容二维码与射频标签）。
      </p>
      <el-form label-width="120px" :model="form" style="margin-top:12px; max-width: 880px;">
        <el-form-item label="所属项目" required>
          <el-select v-model="form.project_id" placeholder="选择项目" style="width:100%;">
            <el-option v-for="p in projects" :key="p.id" :label="`${p.name} (${p.code})`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="构件类型">
          <el-select v-model="form.component_type" style="width:100%;">
            <el-option label="外墙板" value="外墙板" />
            <el-option label="内墙板" value="内墙板" />
            <el-option label="叠合楼板" value="叠合楼板" />
            <el-option label="楼梯" value="楼梯" />
            <el-option label="预制梁" value="预制梁" />
            <el-option label="预制柱" value="预制柱" />
            <el-option label="预制阳台" value="预制阳台" />
            <el-option label="整体卫浴" value="整体卫浴" />
          </el-select>
        </el-form-item>
        <el-form-item label="规格型号">
          <el-input v-model="form.spec" placeholder="例如 YGW-外墙板-3.0m×6.0m" />
        </el-form-item>
        <el-form-item label="模具编号">
          <el-input v-model="form.mould_no" placeholder="例如 M-001" />
        </el-form-item>
        <el-form-item label="钢筋批号">
          <el-input v-model="form.rebar_batch" placeholder="例如 RB-2025-001" />
        </el-form-item>
        <el-form-item label="混凝土配合比">
          <el-input v-model="form.concrete_ratio" />
        </el-form-item>
        <el-form-item label="浇筑时间">
          <el-input v-model="form.pour_at" type="datetime-local" />
        </el-form-item>
        <el-form-item label="养护记录">
          <el-input v-model="form.curing_record" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="强度报告">
          <el-input v-model="form.strength_report" placeholder="例如 STR-2025-001" />
        </el-form-item>
        <el-form-item label="出厂自检结论">
          <el-radio-group v-model="form.factory_inspection">
            <el-radio-button value="合格">合格</el-radio-button>
            <el-radio-button value="不合格">不合格</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-button type="primary" @click="submit">生成追溯码并提交</el-button>
      </el-form>
    </div>

    <div class="card-section">
      <h3>本工厂已录入构件</h3>
      <el-table :data="components" border stripe>
        <el-table-column prop="trace_code" label="追溯码" width="220" />
        <el-table-column prop="rfid_tag" label="RFID 标签" width="180" />
        <el-table-column prop="component_type" label="类型" width="100" />
        <el-table-column prop="spec" label="规格" />
        <el-table-column prop="mould_no" label="模具" width="100" />
        <el-table-column prop="rebar_batch" label="钢筋批号" width="140" />
        <el-table-column prop="current_stage" label="当前阶段" width="120" />
        <el-table-column label="二维码" width="120">
          <template #default="{ row }">
            <el-link :href="`/trace/${row.trace_code}`" target="_blank">查看追溯</el-link>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
