<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { componentApi, qualityApi } from '@/api'

const tasks = ref<any[]>([])
const components = ref<any[]>([])

// 选中的任务
const selectedTask = ref<any | null>(null)
const taskDetail = ref<any | null>(null)

const form = reactive({
  component_id: undefined as number | undefined,
  stage: '已进场',
  title: '',
  requirement: '',
  planned_at: '',
})

async function load() {
  tasks.value = (await qualityApi.listTasks({ only_open: true })).data
  components.value = (await componentApi.list()).data
}

async function loadDetail(taskId: number) {
  selectedTask.value = tasks.value.find(t => t.id === taskId) || null
  taskDetail.value = (await qualityApi.getTask(taskId)).data
}

async function createTask() {
  if (!form.component_id) {
    ElMessage.warning('请选择构件')
    return
  }
  await qualityApi.createTask({
    ...form,
    planned_at: form.planned_at
      ? new Date(form.planned_at).toISOString()
      : null,
  })
  ElMessage.success('抽检任务已发起，自动派单到现场抽检员')
  await load()
}

async function closeTask(task: any) {
  try {
    await ElMessageBox.confirm(
      `确认关闭抽检任务 ${task.task_no}？关闭后该工序可重新发起抽检。`,
      '提示', { type: 'warning' },
    )
  } catch { return }
  task.is_closed = true
  ElMessage.success('已标记为关闭（实际闭环由复核决定）')
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>质监工作台 · 抽检任务发起</h3>
      <p style="color:#909399; font-size:13px;">
        质监账号在政务工作台发起抽检任务，关联具体构件与工序，任务自动派单到现场抽检员。
        现场抽检完成后结论实时回传；不合格时系统自动开整改并阻断下游工序。
      </p>
      <el-form label-width="120px" :model="form" style="max-width:760px; margin-top:12px;">
        <el-form-item label="抽检构件" required>
          <el-select v-model="form.component_id" filterable placeholder="选择构件" style="width:100%;">
            <el-option
              v-for="c in components"
              :key="c.id"
              :value="c.id"
              :label="`${c.trace_code} (${c.spec}, 当前阶段：${c.current_stage})`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="抽检工序" required>
          <el-select v-model="form.stage" style="width:100%;">
            <el-option value="已生产" label="构件生产" />
            <el-option value="运输中" label="运输途中" />
            <el-option value="已进场" label="进场验收" />
            <el-option value="已吊装" label="吊装" />
            <el-option value="节点连接" label="节点连接" />
            <el-option value="已隐蔽" label="隐蔽前" />
            <el-option value="成品保护" label="成品保护" />
            <el-option value="已归档" label="档案归档" />
          </el-select>
        </el-form-item>
        <el-form-item label="抽检标题">
          <el-input v-model="form.title" placeholder="如：屋面防水节点抽检" />
        </el-form-item>
        <el-form-item label="抽检要求">
          <el-input v-model="form.requirement" type="textarea" :rows="2"
            placeholder="应依据的标准、关键控制项等" />
        </el-form-item>
        <el-form-item label="计划抽检时间">
          <el-input v-model="form.planned_at" type="datetime-local" />
        </el-form-item>
        <el-button type="primary" @click="createTask">发起抽检任务</el-button>
      </el-form>
    </div>

    <div class="card-section">
      <h3>未闭环抽检任务</h3>
      <el-table :data="tasks" border @row-click="(row: any) => loadDetail(row.id)">
        <el-table-column prop="task_no" label="任务号" width="220" />
        <el-table-column prop="component_id" label="构件 ID" width="90" />
        <el-table-column prop="stage" label="工序" width="120" />
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="requirement" label="要求" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_closed ? 'success' : 'warning'">
              {{ row.is_closed ? '已闭环' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="发起时间" width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click.stop="loadDetail(row.id)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="taskDetail" class="card-section">
      <h3>抽检任务详情 · {{ taskDetail.task.task_no }}</h3>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="工序">{{ taskDetail.task.stage }}</el-descriptions-item>
        <el-descriptions-item label="构件">
          {{ taskDetail.component?.trace_code }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="taskDetail.task.is_closed ? 'success' : 'warning'">
            {{ taskDetail.task.is_closed ? '已闭环' : '进行中' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <h4 style="margin-top:16px;">抽检记录</h4>
      <el-table :data="taskDetail.records" border size="small">
        <el-table-column prop="sequence" label="次序" width="60" />
        <el-table-column prop="inspected_at" label="抽检时间" width="180" />
        <el-descriptions>
        </el-descriptions>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_reinspection ? 'warning' : 'primary'">
              {{ row.is_reinspection ? '复核' : '抽检' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="conclusion" label="结论" width="100" />
        <el-table-column prop="findings" label="发现" show-overflow-tooltip />
        <el-table-column prop="measures" label="处理措施" show-overflow-tooltip />
      </el-table>
      <h4 style="margin-top:16px;">整改单</h4>
      <el-table :data="taskDetail.rectifications" border size="small">
        <el-table-column prop="round" label="轮次" width="60" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="plan" label="方案" show-overflow-tooltip />
        <el-table-column prop="progress_note" label="过程" show-overflow-tooltip />
        <el-table-column prop="result_note" label="自评" show-overflow-tooltip />
      </el-table>
    </div>
  </div>
</template>
