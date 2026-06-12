const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("timeRecorder", {
  getState: () => ipcRenderer.invoke("state:get"),
  submitRecord: (payload) => ipcRenderer.invoke("record:submit", payload),
  skipRecord: () => ipcRenderer.invoke("record:skip"),
  updateSettings: (patch) => ipcRenderer.invoke("settings:update", patch),
  addPreset: (name) => ipcRenderer.invoke("presets:add", name),
  deletePreset: (index) => ipcRenderer.invoke("presets:delete", index),
  resetPresets: () => ipcRenderer.invoke("presets:reset"),
  clearActivities: () => ipcRenderer.invoke("activities:clear"),
  exportJson: () => ipcRenderer.invoke("export:json"),
  exportCsv: () => ipcRenderer.invoke("export:csv"),
  openLogs: () => ipcRenderer.invoke("logs:open"),
  onStateChanged: (callback) => {
    ipcRenderer.on("state:changed", (_event, snapshot) => callback(snapshot));
  },
  onViewSet: (callback) => {
    ipcRenderer.on("view:set", (_event, view) => callback(view));
  },
});
