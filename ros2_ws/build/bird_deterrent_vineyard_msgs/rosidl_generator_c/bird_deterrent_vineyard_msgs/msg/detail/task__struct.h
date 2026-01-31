// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from bird_deterrent_vineyard_msgs:msg/Task.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_H_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


// Constants defined in the message

// Include directives for member types
// Member 'id'
// Member 'type'
// Member 'assigned_primary'
// Member 'assigned_secondary'
#include "rosidl_runtime_c/string.h"

/// Struct defined in msg/Task in the package bird_deterrent_vineyard_msgs.
typedef struct bird_deterrent_vineyard_msgs__msg__Task
{
  rosidl_runtime_c__String id;
  rosidl_runtime_c__String type;
  double x;
  double y;
  double time;
  rosidl_runtime_c__String assigned_primary;
  rosidl_runtime_c__String assigned_secondary;
  float score;
} bird_deterrent_vineyard_msgs__msg__Task;

// Struct for a sequence of bird_deterrent_vineyard_msgs__msg__Task.
typedef struct bird_deterrent_vineyard_msgs__msg__Task__Sequence
{
  bird_deterrent_vineyard_msgs__msg__Task * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} bird_deterrent_vineyard_msgs__msg__Task__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_H_
