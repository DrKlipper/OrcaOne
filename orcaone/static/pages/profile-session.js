// A shared editor entry point for printer, process and filament pages.
import { go, hashOf } from '../common.js';
export const profileSession = Vue.ref(null);
export function openProfiles(instanceId, profiles = []) {
  profileSession.value = { instanceId, profiles };
  go(null, hashOf('profile-editor', instanceId));
}
export function openProfileBranch(instanceId, branchId) {
  profileSession.value = { instanceId, profiles: [], branchId, selectAll: true };
  go(null, hashOf('profile-editor', instanceId));
}
