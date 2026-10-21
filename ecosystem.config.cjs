module.exports = {
  apps: [{
    name: "aligo",
    cwd: "/opt/aligo",
    script: "/opt/aligo/start.sh",
    interpreter: "/bin/bash",
    env: {
      PYTHONPATH: "/opt/aligo"
    },
    max_memory_restart: "300M",
    autorestart: true
  }]
};
