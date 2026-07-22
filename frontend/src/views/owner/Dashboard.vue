<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { archiveApi, componentApi } from '@/api'

const stats = ref<any>({})
const archives = ref<any[]>([])

async function load() {
  const comps = (await componentApi.list()).data
  const ar = (await archiveApi.list()).data
  archives.value = ar
  const byStage: Record<string, number> = {}
  for (const c of comps) {
    byStage[c.current_stage] = (byStage[c.current_stage] || 0) + 1
  }
  stats.value = { total: comps.length, byStage, archiveCount: ar.length }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>项目总览</h3>
      <el-row :gutter="12">
        <el-col :span="6">
          <el-statistic title="构件总数" :value="stats.total || 0" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="已生成档案" :value="stats.archiveCount || 0" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="已隐蔽验收" :value="(stats.byStage && stats.byStage['已隐蔽']) || 0" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="已归档" :value="(stats.byStage && stats.byStage['成品保护']) || 0" />
        </el-col>
      </el-row>
    </div>
    <div class="card-section">
      <h3>当前阶段分布</h3>
      <el-table :data="Object.entries(stats.byStage || {}).map(([k, v]) => ({ stage: k, count: v }))" border>
        <el-table-column prop="stage" label="阶段" />
        <el-table-column prop="count" label="构件数量" width="120" />
      </el-table>
    </div>
    <div class="card-section">
      <h3>档案列表</h3>
      <el-table :data="archives" border>
        <el-table-column prop="archive_no" label="档案号" width="220" />
        <el-table-column prop="component_id" label="构件 ID" width="100" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="created_at" label="生成时间" width="200" />
      </el-table>
    </div>
  </div>
</template>
