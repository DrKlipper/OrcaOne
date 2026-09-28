export const printerMergeSession = Vue.ref(null);
export function openPrinterMerge(instanceId, names = []) {
  printerMergeSession.value = { instanceId, names };
}
