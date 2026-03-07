---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

**Device Information**
- Device model: (e.g., Bosch CT200, RC300, etc.)
- HA version:
- Bosch component version:
- Protocol: HTTP / XMPP

**POINTT API (if applicable)**
- [ ] POINTT API enabled
- [ ] Issue is related to POINTT/energy data

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1.
2.
3.

**Expected behavior**
A clear and concise description of what you expected to happen.

**Debug Logs**
Enable debug logging and paste relevant logs:
```yaml
logger:
  logs:
    custom_components.bosch: debug
    bosch_thermostat_client: debug
```

**Debug SCAN**
Go to Developer tools → Services → `bosch.debug_scan`
Download file and upload to https://jsonblob.com/

**Screenshots**
If applicable, add screenshots.

**Additional context**
Add any other context about the problem here.
