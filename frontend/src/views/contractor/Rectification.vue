<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { qualityApi } from '@/api'

const rects = ref<any[]>([])

const editForm = reactive<Record<number, any>>({})

async function load() {
  rects.value = (await qualityApi.listRectifications({ only_open: true })).data
  for (const r of rects.value) {
    if (!editForm[r.id]) {
      editForm[r.id] = {
        plan: r.plan || '',
        progress_note: r.progress_note || '',
        result_note: r.result_note || '',
        deadline: r.deadline ? r.deadline.slice(0, 16) : '',
      }
    }
  }
}

async function submitRect(r: any) {
  const f = editForm[r.id]
  await qualityApi.submitRectification({
    task_id: r.task_id,
    plan: f.plan,
    progress_note: f.progress_note,
    deadline: f.deadline ? new Date(f.deadline).toISOString() : null,
  })
  ElMessage.success('整改方案 / 进度已提交')
  await load()
}

async function resubmit(r: any) {
  const f = editForm[r.id]
  if (!f.result_note) {
    ElMessage.warning('请填写自评结果再申请复核')
    return
  }
  await qualityApi.resubmitRectification(r.id, { result_note: f.result_note })
  ElMessage.success('已申请质监复核，等待原抽检人现场复核')
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>整改处理</h3>
      <p style="color:#909399; font-size:13px;">
        质监抽检不合格时，平台自动开整改并阻断下游工序。施工方在此提交整改方案 / 过程，完成后申请复核。
        复核必须由原抽检人完成，复核合格后平台自动解除阻断。
      </p>
    </div>

    <div class="card-section">
      <el-table :data="rects" border>
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="task_id" label="任务 ID" width="100" />
        <el-table-column prop="component_id" label="构件 ID" width="100" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === '已闭环' ? 'success' : 'warning'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="整改信息" min-width="400">
          <template #default="{ row }">
            <el-form label-width="80px" size="small">
              <el-form-item label="方案">
                <el-input v-model="editForm[row.id].plan" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item label="过程">
                <el-input v-model="editForm[row.id].progress_note" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item label="截止">
                <el-input v-model="editForm[row.id].deadline" type="datetime-local" />
              </el-form-item>
              <el-form-item label="自评">
                <el-input v-model="editForm[row.id].result_note"
                  placeholder="完成后请填写自评结果再申请复核" />
              </el-form-item>
              <el-space>
                <el-button size="small" type="primary" @click="submitRect(row)">
                  提交方案/进度
                </el-button>
                <el-button size="small" type="warning" @click="resubmit(row)">
                  申请复核
                </el-button>
              </el-space>
            </el-form>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!rects.length" style="color:#909399; text-align:center; padding:20px;">
        暂无未闭环的整改单
      </div>
    </div>
  </div>
</template>
