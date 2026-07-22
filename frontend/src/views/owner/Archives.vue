<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { archiveApi, componentApi } from '@/api'

const archives = ref<any[]>([])
const components = ref<any[]>([])

async function load() {
  archives.value = (await archiveApi.list()).data
  components.value = (await componentApi.list()).data
}

async function generate(componentId: number) {
  await archiveApi.generate(componentId)
  ElMessage.success('电子档案已生成')
  await load()
}

async function submit(archiveId: number) {
  const r = await archiveApi.submit(archiveId)
  if (r.data.ok) {
    ElMessage.success(`报送成功，质监接收状态 ${r.data.remote_status}`)
  } else {
    ElMessage.warning(`报送被拒，状态 ${r.data.remote_status}`)
  }
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>档案归档</h3>
      <p style="color:#909399; font-size:13px;">按城建档案规范生成电子档案包（ZIP），并通过接口报送至质量监督机构。</p>
      <el-table :data="archives" border>
        <el-table-column prop="archive_no" label="档案号" width="220" />
        <el-table-column prop="component_id" label="构件 ID" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === '已报送' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="生成时间" width="200" />
        <el-table-column prop="submitted_at" label="报送时间" width="200" />
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" :href="archiveApi.downloadUrl(row.id)" target="_blank">下载 ZIP</el-button>
            <el-button size="small" type="primary" :disabled="row.status === '已报送'" @click="submit(row.id)">报送</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="card-section">
      <h3>可生成档案的构件</h3>
      <el-table :data="components.filter(c => c.current_stage === '成品保护' || c.current_stage === '已隐蔽')" border>
        <el-table-column prop="trace_code" label="追溯码" width="220" />
        <el-table-column prop="spec" label="规格" />
        <el-table-column prop="current_stage" label="阶段" width="120" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="generate(row.id)">生成档案</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
