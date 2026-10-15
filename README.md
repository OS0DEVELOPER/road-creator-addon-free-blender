<div align="center">

# 🏔️ Mountain Road Creator V6.3
**Procedural Civil-Engineered Mountain Highways, Elevated Bridges & Offroad Tracks for Blender 4.0+**

[![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/)
[![Version](https://img.shields.io/badge/Release-v6.3.0-007EC6?style=for-the-badge)](https://github.com/OS0DEVELOPER/road-creator-addon-free-blender/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge)](./LICENSE)
[![Game Ready](https://img.shields.io/badge/Engine_Ready-Godot_%7C_Unity_%7C_Unreal-8A2BE2?style=for-the-badge)](#)

<p align="center">
  <b>Draw, extrude, and connect game-ready mountain roads with horizontally level driving decks, anti-underground bridge clamping, continuous W-beam guardrails, and 1-click UV baking.</b>
</p>

</div>

---

## ✨ Key Features in V6.3

* 🛣️ **3 Seamless Road Modes on a Single Network:**
  * **Asphalt Highway:** Horizontally level driving carriageway (`+Z` normal) with subtle drainage camber, procedural lane markings, and retaining embankments that automatically bench into steep mountain cliffs.
  * **Elevated Bridge + Pillars:** Full vertical elevation freedom (`G` + `Z` or live Sidebar Height Controls) with automatic **Anti-Underground Terrain Clamping** so bridges never clip beneath the mountain surface.
  * **Offroad Dirt Track:** Ground-locked mountain trail with adjustable center rut depth and procedural mud/rock displacement.
* 🔗 **True Multi-Bridge Spline Splitting:** Switch freely between `Bridge` ➔ `Offroad` ➔ `Bridge` on the same road without stray guardrail wires or pillars bridging across ground gaps.
* 🛡️ **Continuous W-Beam Guardrails & Custom 3D Assets:**
  * Built-in continuous swept steel crash barriers + posts, or 1-click generation of editable **`Custom_Bridge_2D_Profile`**, **`Custom_Pillar_3D_Mesh`**, and **`Custom_Guardrail_3D_Mesh`** objects.
  * Independent toggles for **Asphalt**, **Bridge**, **Offroad**, **Left Side**, and **Right Side** guardrails.
* 🔀 **Flared Non-Overlapping Intersections (`T`, `Y`, `+`):**
  * Automatically trims branch roads at the main road's curb, flares intersection corners into smooth bell-mouth turns, and clears side barriers and guardrails around junctions.
* 📦 **1-Click Mobile & PC Game Engine Baker:**
  * Converts the procedural Geometry Nodes network into a clean static mesh (`_BakedMesh`) with an active **`UVMap`** layer ready for export to **Godot**, **Unity**, or **Unreal Engine**.

---

## 🚀 Installation

### Method 1: Install as a Blender Add-on (`.zip`)
1. Go to the [**Releases**](https://github.com/OS0DEVELOPER/road-creator-addon-free-blender/releases) page and download **`Mountain_Road_Creator_v6_3.zip`**.
2. Open **Blender 4.0+**, go to **Edit > Preferences > Add-ons**.
3. Click **Install...**, select the downloaded `.zip` file, and enable **Mesh: Mountain Road Creator V6.3**.
4. In the 3D Viewport, press **`N`** and open the **Road Creator** tab.

### Method 2: Run Directly in Scripting Workspace
1. Open Blender's **Scripting** workspace, click **New**, paste the contents of `__init__.py`, and click **Run Script**.

---

## 🎮 Quick-Start Workflow

| Step | Action | Description |
| :--- | :--- | :--- |
| **1. Initialize** | Click **`Build / Upgrade Mountain Road (V6.3)`** | Select your terrain mesh (or name it `Landscape`) and click build to create the procedural road network. |
| **2. Choose Mode** | Click **`Asphalt`**, **`Bridge+Pillars`**, or **`Offroad`** | The active mode button highlights in **Blue**. Any new stroke drawn with **`Draw New Road`** uses this mode automatically. |
| **3. Extrude** | Click **`+ Asphalt`**, **`+ Bridge`**, or **`+ Offroad`** | Select an **Endpoint** in Edit Mode to extend forward, or select a **Middle Point** to branch out at a 90° T-junction. |
| **4. Adjust Bridge Z** | Use **Section 2 (`-5m`, `-1m`, `+1m`, `+5m`)** or `G` + `Z` | Raise or lower selected bridge points. Bridges stop automatically on top of the terrain and never go underground. |
| **5. Custom Assets** | Click **`+ Generate 2D Bridge, 3D Pillar & 3D Guardrail`** | Spawns editable 2D/3D template meshes in your scene and links them to your road modifier automatically. |
| **6. Export / Bake** | Click **`Bake to Mesh + Activate UVMap (Safe)`** | Generates a static mesh with converted UV layers ready for FBX/GLTF export. |

---

## 📐 Civil Engineering & Guardrail Parameters

* **Road Width (m):** Width of the level driving carriageway.
* **Road Camber / Crown Height (m):** Subtle center arch for highway drainage.
* **Superelevation / Banking Angle (deg):** Global curve banking tilt (combines with per-point `Ctrl + T` tilt in Edit Mode).
* **Embankment Slope Spread & Max Drop Depth:** Controls how far and deep retaining dirt walls extend down steep cliffs.
* **Intersection Wall Clear Radius & Corner Flare:** Controls the bell-mouth curve flare and barrier clearing radius at junctions.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE) for full details.