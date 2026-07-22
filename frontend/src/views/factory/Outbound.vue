<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { componentApi, metaApi } from '@/api'

const components = ref<any[]>([])
const transports = ref<any[]>([])
const qrImages = ref<Record<number, string>>({})

const form = reactive({
  component_id: undefined as number | undefined,
  transport_party_id: undefined as number | undefined,
  out_at: new Date().toISOString().slice(0, 16),
  vehicle_no: '',
  driver: '',
  driver_phone: '',
  route_plan: '南京工厂 → 沪宁高速 → 杭州北出口 → 工地临时堆场',
  inspection_conclusion: '合格',
})

async function load() {
  components.value = (await componentApi.list()).data.filter((c: any) => c.current_stage === '已生产')
  transports.value = (await metaApi.parties()).data.filter((p: any) => p.role === 'transport')
  for (const c of components.value) {
    qrImages.value[c.id] = await QRCode.toDataURL(c.qr_payload, { width: 140 })
  }
}

async function submit() {
  if (!form.component_id || !form.transport_party_id) {
    ElMessage.warning('请选择构件与运输单位')
    return
  }
  await componentApi.factoryOut({
    ...form,
    out_at: new Date(form.out_at).toISOString(),
  })
  ElMessage.success('出厂登记成功，已生成随车二维码与出厂合格证')
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card-section">
      <h3>构件出厂登记</h3>
      <p style="color:#909399; font-size:13px; margin-top:4px;">
        工厂端打印构件随车二维码与纸质出厂合格证，向运输单位交接时扫码登记出厂时间、运输车辆、驾驶员、运输路线计划。
      </p>
      <el-form label-width="120px" :model="form" style="max-width:760px; margin-top:12px;">
        <el-form-item label="构件追溯码" required>
          <el-select v-model="form.component_id" filterable placeholder="选择待出厂构件" style="width:100%;">
            <el-option v-for="c in components" :key="c.id" :value="c.id" :label="`${c.trace_code} (${c.spec})`" />
          </el-select>
        </el-form-item>
        <el-form-item label="运输单位" required>
          <el-select v-model="form.transport_party_id" style="width:100%;">
            <el-option v-for="t in transports" :key="t.id" :value="t.id" :label="t.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="出厂时间">
          <el-input v-model="form.out_at" type="datetime-local" />
        </el-form-item>
        <el-form-item label="车牌号"><el-input v-model="form.vehicle_no" /></el-form-item>
        <el-form-item label="驾驶员"><el-input v-model="form.driver" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.driver_phone" /></el-form-item>
        <el-form-item label="运输路线计划"><el-input v-model="form.route_plan" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="出厂检验结论">
          <el-radio-group v-model="form.inspection_conclusion">
            <el-radio-button value="合格">合格</el-radio-button>
            <el-radio-button value="不合格">不合格</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-button type="primary" @click="submit">提交出厂登记</el-button>
      </el-form>
    </div>

    <div class="card-section">
      <h3>已录入构件的随车二维码（兼容 RFID 标签）</h3>
      <el-table :data="components" border>
        <el-table-column prop="trace_code" label="追溯码" width="220" />
        <el-table-column prop="rfid_tag" label="RFID 标签" width="180" />
        <el-table-column prop="spec" label="规格" />
        <el-table-column label="随车二维码" width="180">
          <template #default="{ row }">
            <img v-if="qrImages[row.id]" :src="qrImages[row.id]" alt="qrcode" style="width:80px; height:80px;" />
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
