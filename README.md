# VoiceGo — Voice-first ride-hailing for visually impaired users

## 🔗 Live demo

> ### https://voicego-9k11.onrender.com
>
> Runs in the browser on both phone and desktop — nothing to install.
> Best on **Chrome for Android** (full vibration + screen-flash beacon support).
> Allow **Microphone** and **Location** when prompted, then just say where you want to go.
>
> Step-by-step walkthrough: [voicego/DEMO.md](voicego/DEMO.md) ·
> Architecture: [voicego/ARCHITECTURE.md](voicego/ARCHITECTURE.md)

---

# Problem Statement

## Context

For many people with disabilities, completing everyday tasks can be significantly more challenging than for the general population. One such challenge is using ride-hailing applications, which rely heavily on visual interfaces and precise touch interactions.

In this project, we aim to improve the ride-hailing experience for people with disabilities. For the first version (MVP), our solution specifically focuses on **visually impaired users**, who face the greatest accessibility barriers when interacting with existing ride-hailing applications.

---

## Target Users

**Primary Target Users**

- People with disabilities who rely on ride-hailing services for daily transportation.
- **MVP Focus:** Visually impaired users through a dedicated Accessibility Mode.
- **Future Expansion:** Support for other user groups, including people with hearing impairments and mobility disabilities.

---

## User Journey & Pain Points

Through user research, we analyzed the end-to-end journey of visually impaired users when booking and taking a ride. The findings reveal several pain points across every stage of the experience.

### 1. Booking a Ride

**Current Behavior**

Users rely on screen readers such as **VoiceOver** or **TalkBack** to navigate the app and complete the booking process.

**Pain Points**

- Screen readers announce content sequentially, forcing users to navigate through every interface element before reaching the desired action.
- Small buttons and dense layouts make interactions slow and difficult.
- Booking a ride becomes time-consuming, frustrating, and cognitively demanding.

---

### 2. Identifying the Driver

**Current Behavior**

Users often ask nearby pedestrians to verify the license plate or vehicle details, while drivers confirm the passenger's name and destination verbally.

**Pain Points**

- Users constantly worry about getting into the wrong vehicle.
- Assistance from nearby people is not always available.
- The inability to independently verify the driver introduces potential safety risks.

---

### 3. During the Trip

**Current Behavior**

Most ride-hailing applications present trip progress primarily through visual maps.

**Pain Points**

- Screen readers provide little or no meaningful information about the driver's route.
- Users cannot tell whether the driver is following the correct route.
- The lack of real-time trip awareness reduces users' sense of safety and control throughout the journey.

---

### 4. Arriving at the Destination

**Current Behavior**

Drivers usually drop passengers off at the exact pin location selected in the app.

**Pain Points**

- Some destinations have entrances that are significantly more accessible for visually impaired users.
- Drivers are often unaware of these accessible drop-off points.
- Users receive no guidance on where the safest or most convenient drop-off location is.

# Solution Overview

## Our Solution

An **accessible ride-hailing experience** designed specifically for visually impaired users.

Rather than redesigning the entire ride-hailing workflow, our solution introduces an **Accessibility Mode** that simplifies interactions, enhances user safety, and enables greater independence throughout the journey.

---

## Goals

- Simplify the ride-booking process through accessible interactions.
- Enable visually impaired users to travel more independently.
- Improve passenger safety before, during, and after each trip.
- Reduce reliance on assistance from surrounding people.
- Deliver a more inclusive and equitable mobility experience.

---

## Key Ideas

### 🎙️ Voice-based Ride Booking

Allow users to book rides naturally using voice commands instead of navigating complex interfaces.

### 📍 Accessible Destination Recommendations

Recommend safer and more accessible pickup and drop-off locations based on the destination, helping both drivers and passengers choose the most suitable access point.

### 🔐 Driver Verification with a Secure PIN

Require both the passenger and driver to verify a shared PIN before the trip begins, ensuring that users board the correct vehicle.

### 🗺️ Voice-guided Trip Tracking

Provide spoken updates about trip progress, estimated arrival time, and route status so users can stay informed throughout the journey.

---

## Value Proposition

Our solution goes beyond making ride-hailing applications **usable** for visually impaired users—it aims to make them **safe, intuitive, and empowering**.

By combining accessibility-first interaction design with safety-focused features, we help visually impaired users travel with greater confidence, independence, and peace of mind.


---


## Feature

### 🎙️ Feature 1 - Voice-based Ride Booking

**Description**

Allows users to book a ride entirely through voice commands without interacting with the screen. The AI processes the user's request, confirms the pickup location, destination, and ride type through natural conversation, making Grab more accessible for visually impaired users.

**User Flow**

1. The user activates **Đặt chuyến bằng giọng nói**.
2. The user states their desired destination.
3. The AI suggests available ride options.
4. The AI confirms the pickup location, destination, and selected fare.
5. The user confirms the booking.
6. The system creates the ride request and announces the driver's information.


### 📍 Feature 2 - Accessible Destination Recommendations

**Description**

The AI recommends destinations and pickup/drop-off points that are more accessible for visually impaired users. It prioritizes locations with safe walking paths, clearly designated pickup areas, and places verified by Grab or the community. If the selected location is difficult to access, the system suggests nearby alternatives.

**User Flow**

1. The user enters or speaks their destination.
2. The AI evaluates the accessibility of the destination.
3. The system displays more accessible nearby destinations or pickup points.
4. The user selects one of the recommended locations.
5. The ride booking process continues.


### 🔐 Feature 3 - Driver Verification with a Secure PIN

**Description**

To prevent users from boarding the wrong vehicle, the system generates a unique PIN for each trip. After the driver arrives, the passenger shares the PIN with the driver. The trip can only begin once the correct PIN has been entered and verified.

**User Flow**

1. After the driver confirms arrival at the pickup location, the system generates a unique PIN for the trip.
2. The user receives the PIN through voice guidance.
3. The driver enters the PIN into the system.
4. The system verifies the PIN.
5. If the PIN is correct, the trip is confirmed.
6. The user boards the vehicle and begins the journey safely.


## References

- User interview records: https://drive.google.com/file/d/1Ulro0xne8gwVoT0kMiwNmzdKeDphyhUJ/view?usp=sharing


(LINK: https://docs.google.com/spreadsheets/d/1kul9LhGJu0Gap3uZgWiEGo3gmceUtxT_cPT1FAsvziY/edit?gid=1628566515#gid=1628566515)

mô hình Double Diamond