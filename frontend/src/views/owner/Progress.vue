<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { metaApi, projectApi } from '@/api'

const projects = ref<any[]>([])
const selectedProjectId = ref<number | null>(null)
const progress = ref<any | null>(null)
const view = ref<'gantt' | 'kanban' | 'map'>('gantt')

async function loadProjects() {
  projects.value = (await metaApi.projects()).data
  if (projects.value.length && !selectedProjectId.value) {
    selectedProjectId.value = projects.value[0].id
  }
}

async function loadProgress() {
  if (!selectedProjectId.value) return
  progress.value = (await projectApi.getProgress(selectedProjectId.value)).data
}

const stageOrder = [
  '已生产', '运输中', '已到场', '已进场', '已吊装',
  '节点连接', '已隐蔽', '成品保护', '已归档',
]
const stageColors: Record<string, string> = {
  '已生产': '#94a3b8', '运输中': '#3b82f6', '已到场': '#0ea5e9',
  '已进场': '#10b981', '已吊装': '#22c55e', '节点连接': '#84cc16',
  '已隐蔽': '#eab308', '成品保护': '#f59e0b', '已归档': '#1d4ed8',
}
const milestoneColors: Record<string, string> = {
  'PENDING': '#94a3b8', 'ON_TRACK': '#3b82f6', 'ACHIEVED': '#10b981',
  'DELAYED': '#f59e0b', 'BLOCKED': '#ef4444',
}

const kanbanColumns = computed(() => {
  if (!progress.value) return []
  return stageOrder
    .filter(s => (progress.value!.stage_buckets[s] || 0) > 0)
    .map(s => ({
      stage: s,
      count: progress.value!.stage_buckets[s] || 0,
      color: stageColors[s] || '#94a3b8',
    }))
})

// 地图：以地图中心为原点，把所有坐标按比例归一化到视口
const mapBounds = computed(() => {
  if (!progress.value?.locations?.length) {
    return { minLng: 119.9, maxLng: 120.2, minLat: 29.9, maxLat: 30.2 }
  }
  const l = progress.value.locations
  return {
    minLng: Math.min(...l.map((x: any) => x.longitude)) - 0.01,
    maxLng: Math.max(...l.map((x: any) => x.longitude)) + 0.01,
    minLat: Math.min(...l.map((x: any) => x.latitude)) - 0.01,
    maxLat: Math.max(...l.map((x: any) => x.latitude)) + 0.01,
  }
})

function pointStyle(loc: any) {
  const { minLng, maxLng, minLat, maxLat } = mapBounds.value
  const x = ((loc.longitude - minLng) / (maxLng - minLng)) * 100
  const y = 100 - ((loc.latitude - minLat) / (maxLat - minLat)) * 100
  return { left: `${x}%`, top: `${y}%` }
}

function statusLabel(s: string) {
  return {
    PENDING: '未启动', ON_TRACK: '进行中', ACHIEVED: '已达成',
    DELAYED: '延期', BLOCKED: '被阻断',
  }[s] || s
}

onMounted(async () => {
  await loadProjects()
  await loadProgress()
})
</script>

<template>
  <div>
    <div class="card-section">
      <h3>项目进度可视化</h3>
      <p style="color:#909399; font-size:13px;">
        按项目汇总各构件当前阶段、整体完成度、关键节点达成情况，提供
        <b>甘特图</b> / <b>看板</b> / <b>地图</b> 三种视图。三视图共享同一数据源，确保建设方、施工方、监理方、质监方看到一致结果。
      </p>
      <el-space style="margin-top:8px;">
        <el-select v-model="selectedProjectId" placeholder="选择项目" style="width:240px;"
          @change="loadProgress">
          <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.name" />
        </el-select>
        <el-radio-group v-model="view" size="large">
          <el-radio-button value="gantt">甘特图</el-radio-button>
          <el-radio-button value="kanban">看板</el-radio-button>
          <el-radio-button value="map">地图</el-radio-button>
        </el-radio-group>
      </el-space>
    </div>

    <div v-if="progress" class="card-section">
      <el-row :gutter="12">
        <el-col :span="6">
          <el-statistic title="整体完成度" :value="progress.overall_pct" suffix="%" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="未闭环抽检" :value="progress.inspection_open" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="未闭环整改" :value="progress.rect_open" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="被阻断构件" :value="progress.blocked_components" />
        </el-col>
      </el-row>
    </div>

    <!-- 甘特图 -->
    <div v-if="view === 'gantt' && progress" class="card-section">
      <h3>关键节点 · 甘特视图</h3>
      <el-table :data="progress.milestones" border>
        <el-table-column prop="milestone.sort_no" label="#" width="50" type="index" />
        <el-table-column prop="milestone.name" label="节点" width="180" />
        <el-table-column prop="milestone.stage" label="对应工序" width="120" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :color="milestoneColors[row.status]">
              <span style="color:#fff;">{{ statusLabel(row.status) }}</span>
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划日期" width="180">
          <template #default="{ row }">
            {{ row.milestone.planned_at || '未排期' }}
          </template>
        </el-table-column>
        <el-table-column label="达成率" width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.progress_pct" :status="
              row.status === 'ACHIEVED' ? 'success' :
              row.status === 'BLOCKED' ? 'exception' : ''" />
          </template>
        </el-table-column>
        <el-table-column label="被阻断构件" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.blocked_components > 0" type="danger">
              {{ row.blocked_components }} 件
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 看板 -->
    <div v-if="view === 'kanban' && progress" class="card-section">
      <h3>构件阶段分布 · 看板视图</h3>
      <div class="kanban">
        <div v-for="col in kanbanColumns" :key="col.stage" class="kanban-col">
          <div class="kanban-col-header" :style="{ background: col.color }">
            <span>{{ col.stage }}</span>
            <el-tag size="small">{{ col.count }}</el-tag>
          </div>
          <div class="kanban-col-body">
            <div v-for="i in col.count" :key="i" class="kanban-card">
              <div class="dot" :style="{ background: col.color }"></div>
              <span>构件 #{{ i }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 地图 -->
    <div v-if="view === 'map' && progress" class="card-section">
      <h3>构件工地位置 · 地图视图</h3>
      <p style="color:#909399; font-size:13px;">
        每个点代表一个构件的实际位置，由吊装坐标 / 维护检查坐标自动汇总。
        地图数据按比例渲染（无外部地图服务依赖）。
      </p>
      <div class="map-canvas">
        <div
          v-for="loc in progress.locations"
          :key="loc.id"
          class="map-pin"
          :style="pointStyle(loc)"
          :title="`构件 ${loc.component_id} · ${loc.building} ${loc.floor}`"
        >
          <div class="pin-dot"></div>
          <div class="pin-tip">{{ loc.building }} {{ loc.floor }}</div>
        </div>
        <div v-if="!progress.locations.length" class="map-empty">
          暂无构件坐标数据，请先在吊装 / 维护模块登记
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kanban {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 8px;
}
.kanban-col {
  flex: 0 0 200px;
  background: #f5f7fa;
  border-radius: 6px;
  overflow: hidden;
}
.kanban-col-header {
  color: #fff;
  padding: 8px 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.kanban-col-body {
  padding: 8px;
  min-height: 120px;
}
.kanban-card {
  background: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.map-canvas {
  position: relative;
  width: 100%;
  height: 480px;
  background:
    linear-gradient(rgba(99,102,241,0.06) 1px, transparent 1px) 0 0 / 40px 40px,
    linear-gradient(90deg, rgba(99,102,241,0.06) 1px, transparent 1px) 0 0 / 40px 40px,
    linear-gradient(135deg,#eef2ff,#f0fdfa);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}
.map-pin {
  position: absolute;
  transform: translate(-50%, -100%);
  cursor: pointer;
}
.pin-dot {
  width: 14px; height: 14px;
  background: #1d4ed8;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}
.pin-tip {
  display: none;
  position: absolute;
  left: 18px; top: -4px;
  background: #1f2937;
  color: #fff;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  white-space: nowrap;
}
.map-pin:hover .pin-tip { display: block; }
.map-empty {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  color: #94a3b8;
  font-size: 14px;
}
</style>
