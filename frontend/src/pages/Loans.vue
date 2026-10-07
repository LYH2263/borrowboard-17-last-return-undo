<template>
  <div style="padding:16px">
    <h1>借还记录</h1>
    <p v-if="err" class="err">{{ err }}</p>
    <p v-if="ok" class="muted">{{ ok }}</p>

    <h3>逾期</h3>
    <div v-for="l in data.overdue" :key="'o'+l.id" class="item overdue">
      {{ l.title }} · {{ l.borrower }}
      <span v-if="l.undone_at" class="muted">（撤销归还恢复：{{ l.undo_reason }} · {{ dispLabel(l.undo_disposition) }}）</span>
    </div>
    <h3>在借</h3>
    <div v-for="l in data.active" :key="'a'+l.id" class="item">
      {{ l.title }} · {{ l.borrower }}
      <span v-if="l.undone_at" class="muted">（撤销归还恢复：{{ l.undo_reason }} · {{ dispLabel(l.undo_disposition) }}）</span>
    </div>
    <h3>已还</h3>
    <div v-for="l in data.returned" :key="'r'+l.id" class="item">
      {{ l.title }} · {{ l.borrower }}
      <button v-if="l.id === latestReturnedId" @click="openUndo(l)">撤销归还</button>
      <span v-else class="muted">（历史已还，不可撤销）</span>
    </div>
    <h3 v-if="data.bumped && data.bumped.length">已挤掉</h3>
    <div v-for="l in data.bumped" :key="'b'+l.id" class="item">
      {{ l.title }} · {{ l.borrower }}
      <span class="muted">（被撤销归还 #{{ l.bumped_by }} 挤掉）</span>
    </div>

    <div v-if="undo" class="item undo-box">
      <h4>撤销归还 #{{ undo.loan.id }} · {{ undo.loan.title }}</h4>
      <input v-model="undo.reason" placeholder="原因字（必填）" />
      <button @click="preview">预览</button>
      <button @click="undo = null">取消</button>
      <div v-if="undo.preview">
        <p v-if="!undo.preview.ok" class="err">预览失败：{{ undo.preview.reason }}</p>
        <template v-else>
          <p class="muted">预览不落库，可借栏集合不变。</p>
          <template v-if="undo.preview.conflict">
            <p>该物已被 {{ undo.preview.blocking_loan && undo.preview.blocking_loan.borrower }} 借出通过，选择冲突处置：</p>
            <label><input type="radio" value="fail" v-model="undo.disposition" /> 整单失败保持现况</label>
            <label><input type="radio" value="bump" v-model="undo.disposition" /> 挤掉新借让原笔回到在借</label>
          </template>
          <p v-else>无冲突：确认后该笔回到在借栏。</p>
          <button @click="confirm">确认撤销</button>
        </template>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, inject, onMounted } from 'vue'
import { api } from '../api'
const data = ref({ active: [], overdue: [], returned: [], bumped: [] })
const reloadBoard = inject('reloadBoard')
const undo = ref(null)
const err = ref('')
const ok = ref('')
const latestReturnedId = computed(() => {
  const rs = data.value.returned.filter(l => l.returned_at)
    .sort((a, b) => String(b.returned_at).localeCompare(String(a.returned_at)) || b.id - a.id)
  return rs.length ? rs[0].id : null
})
async function load() { data.value = await api('/loans') }
function openUndo(l) {
  err.value = ''; ok.value = ''
  undo.value = { loan: l, reason: '', disposition: 'fail', preview: null }
}
async function preview() {
  err.value = ''
  try {
    undo.value.preview = await api('/loans/' + undo.value.loan.id + '/undo-return/preview',
      { method: 'POST', body: JSON.stringify({ reason: undo.value.reason }) })
  } catch (e) { err.value = '预览失败：' + e.message }
}
async function confirm() {
  err.value = ''; ok.value = ''
  try {
    await api('/loans/' + undo.value.loan.id + '/undo-return',
      { method: 'POST', body: JSON.stringify({ reason: undo.value.reason, disposition: undo.value.disposition }) })
    ok.value = '已撤销归还，该笔回到在借栏'
    undo.value = null
    await load()
    if (reloadBoard) await reloadBoard()
  } catch (e) { err.value = '撤销失败：' + e.message }
}
function dispLabel(d) { return d === 'bump' ? '挤掉新借' : '整单失败保持现况' }
onMounted(load)
</script>
<style scoped>
.undo-box { border: 2px solid var(--accent); }
.undo-box label { display: block; margin: 4px 0; }
.undo-box input[type="radio"] { width: auto; margin: 0 6px 0 0; }
.err { color: #a33; }
</style>
