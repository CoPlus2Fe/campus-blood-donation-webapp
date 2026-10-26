---
name: 热血行动
description: 某高校无偿献血健康公益嘉年华的参与者与工作人员界面
colors:
  night: "#071522"
  surface: "#102533"
  raised-surface: "#17303d"
  line: "#35505a"
  ink: "#f6f1e8"
  muted: "#b6cbc9"
  warm-red: "#ff7480"
  leaf-teal: "#73d9bf"
  warm-gold: "#f3ce8b"
  action-red: "#b63748"
  staff-ground: "#141c24"
  staff-surface: "#202c35"
rounded:
  control: "6px"
  panel: "8px"
spacing:
  compact: "8px"
  section: "20px"
components:
  button-primary:
    backgroundColor: "{colors.action-red}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "42px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
---

## Overview

深色活动记分界面结合校园公益插画与克制的竞技状态。参与者端突出血值、能量、项目进度与可操作的下一步；工作人员端采用更密集、便于核对的列表和表单。游戏感来自分数、状态、幸运轮与色彩节奏，不把献血描述为冒险。

## Colors

- 深夜蓝用于页面底色，略浅的蓝绿用于列表与操作表面。
- 暖红表示活动身份、血值和主要操作；青绿表示能量、完成状态；金色提示奖品与焦点。
- 工作人员端使用独立的深灰蓝背景，维持与参与者端相同的红、青绿、金语义。

## Typography

中文以系统无衬线字体栈为主体。活动名称和页面标题使用较粗字重；数字使用等宽数字特性，便于对比分数。短标签与辅助信息不代替明确的按钮名称。

## Layout

参与者端限制在约 600px 宽的移动优先画布，底部五项导航固定；注册字段按单列阅读顺序排列。工作人员端扩展到约 1180px 宽，页面按核验、流水、参与者、兑换、项目、奖品和账号组织。窄屏时表单换列，记录操作保持可触达。

## Elevation & Depth

页面主要通过表面明度与细边线区分层级；重要按钮和浮层使用柔和、向下偏移的阴影。避免发光装饰覆盖个人信息与任务内容。

## Shapes

输入、按钮与面板使用小圆角。幸运轮保留真实扇区比例与固定指针；身份选择是单选控件，项目授权是多选控件。

## Components

- **主按钮：** 暖红填充，显示明确操作；禁用、悬停与键盘焦点有可见区别。
- **数据行：** 工作人员核验记录显示姓名、编号、项目、状态、时间和实际结算；修改与撤回紧邻原记录。
- **资源状态：** 血值与能量分别使用暖红和青绿，余额与累计成绩不混用。
- **弹窗：** 仅用于项目详情等需要集中确认的交互，更正操作要求填写原因。

## Do's and Don'ts

### Do:

- **Do** 将现场活动事实、奖励规则和北京时间限制放在操作附近。
- **Do** 在工作人员界面直接展示当前账号权限与项目筛选。

### Don't:

- **Don't** 以视觉隐藏替代服务端权限校验。
