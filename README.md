# De Anza College Course Monitor

A tool for monitoring De Anza College course availability, saving course data, and finding courses. The project is being developed toward a Telegram Bot service.

**Status: In development.** Real-time monitoring, data saving, and course lookup are implemented. Telegram Bot notifications are not yet implemented. Mailgun is no longer used.

## Current Features

- **Real-time monitoring:** Monitor course availability as it changes.
- **Data saving:** Save collected course data.
- **Course lookup:** Find courses using the implemented lookup functionality.

These capabilities describe the current project functionality. They do not imply that each feature is already available through Telegram.

## Telegram Bot Development

The Telegram Bot service is currently being built. The next planned capability is sending course availability notifications through Telegram.

| Capability | Status |
| --- | --- |
| Real-time course monitoring | Implemented |
| Saving course data | Implemented |
| Finding courses | Implemented |
| Telegram Bot service | In development |
| Telegram Bot notifications | Not implemented |
| Mailgun email notifications | No longer used |

**The current version does not send Telegram Bot notifications.** Monitoring and saving data should not be treated as confirmation that an alert will be delivered.

## Roadmap

- [x] Implement real-time course monitoring
- [x] Implement course data saving
- [x] Implement course lookup
- [ ] Complete the Telegram Bot service
- [ ] Implement Telegram Bot notifications for course availability changes
- [ ] Document Telegram setup and supported commands as they become available

## Project Scope

This project focuses on course monitoring, data collection, and course lookup. Planned notification features will help users learn about availability changes through Telegram.

## Documentation Status

Setup instructions and Telegram Bot commands will be documented as the service takes shape. Earlier instructions referring to Mailgun are obsolete and do not describe the current project.
