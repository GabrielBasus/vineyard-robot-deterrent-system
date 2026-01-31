// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/TaskStatus.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'event'
// Member 'robot_id'
// Member 'task_id'
// Member 'type'
// Member 'role'
// Member 'extra'
#include "rosidl_runtime_c/string.h"

/// Struct defined in msg/TaskStatus in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__TaskStatus
{
  double t;
  rosidl_runtime_c__String event;
  rosidl_runtime_c__String robot_id;
  rosidl_runtime_c__String task_id;
  rosidl_runtime_c__String type;
  double x;
  double y;
  rosidl_runtime_c__String role;
  rosidl_runtime_c__String extra;
} bird_deterrent_vineyard_msgs__msg__TaskStatus;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__TaskStatus.
typedef struct bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence
{
  bird_deterrent_vineyard_msgs__msg__TaskStatus * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__STRUCT_H_
