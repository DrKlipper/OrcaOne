import ProfileEditor from './profile-editor.js';
import { profileSession } from './profile-session.js';
import { setLeaveGuard, clearLeaveGuard } from '../common.js';
import { T } from '../texts.js';

export default {
  name: 'ProfileEditorPage',
  components: { ProfileEditor },
  props: { instId: { type: String, required: true } },
  emits: ['applied'],
  setup(props) {
    const pending = Vue.ref(false), running = Vue.ref(false);
    const leaveMessage = () => running.value ? T.profileEditor.leaveRunning : T.profileEditor.discard;
    let acceptedHash = window.location.hash;
    const guarded = step => { if (!pending.value || window.confirm(leaveMessage())) step(); };
    const beforeUnload = event => {
      if (pending.value) { event.preventDefault(); event.returnValue = ''; }
    };
    const hashChanged = event => {
      if (pending.value && !window.confirm(leaveMessage())) {
        event.stopImmediatePropagation();
        window.history.replaceState(null, '', acceptedHash);
      } else acceptedHash = window.location.hash;
    };
    Vue.onMounted(() => {
      setLeaveGuard(guarded);
      window.addEventListener('beforeunload', beforeUnload);
      window.addEventListener('hashchange', hashChanged, true);
    });
    Vue.onUnmounted(() => {
      clearLeaveGuard(guarded);
      window.removeEventListener('beforeunload', beforeUnload);
      window.removeEventListener('hashchange', hashChanged, true);
    });
    if (!profileSession.value || profileSession.value.instanceId !== props.instId) {
      let branchId;
      try { branchId = window.localStorage?.getItem('orcaone.editor.branch.' + props.instId) || undefined; } catch { /* Storage may be unavailable. */ }
      profileSession.value = { instanceId: props.instId, profiles: [], branchId, selectAll: true };
    }
    return { pending, running };
  },
  template: `<div class="page profile-editor-page"><ProfileEditor :embedded="true" @pending="pending = $event" @running="running = $event" @applied="$emit('applied')"/></div>`,
};
