// generated from rosidl_typesupport_introspection_c/resource/idl__type_support.c.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice

#include <stddef.h>
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__rosidl_typesupport_introspection_c.h"
#include "bird_deterrent_vineyard_msgs/msg/rosidl_typesupport_introspection_c__visibility_control.h"
#include "rosidl_typesupport_introspection_c/field_types.h"
#include "rosidl_typesupport_introspection_c/identifier.h"
#include "rosidl_typesupport_introspection_c/message_introspection.h"
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__functions.h"
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.h"


// Include directives for member types
// Member `robot_id`
// Member `neighbors`
#include "rosidl_runtime_c/string_functions.h"
// Member `polygon`
#include "bird_deterrent_vineyard_msgs/msg/polygon2_d.h"
// Member `polygon`
#include "bird_deterrent_vineyard_msgs/msg/detail/polygon2_d__rosidl_typesupport_introspection_c.h"

#ifdef __cplusplus
extern "C"
{
#endif

void bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_init_function(
  void * message_memory, enum rosidl_runtime_c__message_initialization _init)
{
  // TODO(karsten1987): initializers are not yet implemented for typesupport c
  // see https://github.com/ros2/ros2/issues/397
  (void) _init;
  bird_deterrent_vineyard_msgs__msg__Zone__init(message_memory);
}

void bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_fini_function(void * message_memory)
{
  bird_deterrent_vineyard_msgs__msg__Zone__fini(message_memory);
}

size_t bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__size_function__Zone__neighbors(
  const void * untyped_member)
{
  const rosidl_runtime_c__String__Sequence * member =
    (const rosidl_runtime_c__String__Sequence *)(untyped_member);
  return member->size;
}

const void * bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_const_function__Zone__neighbors(
  const void * untyped_member, size_t index)
{
  const rosidl_runtime_c__String__Sequence * member =
    (const rosidl_runtime_c__String__Sequence *)(untyped_member);
  return &member->data[index];
}

void * bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_function__Zone__neighbors(
  void * untyped_member, size_t index)
{
  rosidl_runtime_c__String__Sequence * member =
    (rosidl_runtime_c__String__Sequence *)(untyped_member);
  return &member->data[index];
}

void bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__fetch_function__Zone__neighbors(
  const void * untyped_member, size_t index, void * untyped_value)
{
  const rosidl_runtime_c__String * item =
    ((const rosidl_runtime_c__String *)
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_const_function__Zone__neighbors(untyped_member, index));
  rosidl_runtime_c__String * value =
    (rosidl_runtime_c__String *)(untyped_value);
  *value = *item;
}

void bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__assign_function__Zone__neighbors(
  void * untyped_member, size_t index, const void * untyped_value)
{
  rosidl_runtime_c__String * item =
    ((rosidl_runtime_c__String *)
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_function__Zone__neighbors(untyped_member, index));
  const rosidl_runtime_c__String * value =
    (const rosidl_runtime_c__String *)(untyped_value);
  *item = *value;
}

bool bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__resize_function__Zone__neighbors(
  void * untyped_member, size_t size)
{
  rosidl_runtime_c__String__Sequence * member =
    (rosidl_runtime_c__String__Sequence *)(untyped_member);
  rosidl_runtime_c__String__Sequence__fini(member);
  return rosidl_runtime_c__String__Sequence__init(member, size);
}

static rosidl_typesupport_introspection_c__MessageMember bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_member_array[3] = {
  {
    "robot_id",  // name
    rosidl_typesupport_introspection_c__ROS_TYPE_STRING,  // type
    0,  // upper bound of string
    NULL,  // members of sub message
    false,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs__msg__Zone, robot_id),  // bytes offset in struct
    NULL,  // default value
    NULL,  // size() function pointer
    NULL,  // get_const(index) function pointer
    NULL,  // get(index) function pointer
    NULL,  // fetch(index, &value) function pointer
    NULL,  // assign(index, value) function pointer
    NULL  // resize(index) function pointer
  },
  {
    "polygon",  // name
    rosidl_typesupport_introspection_c__ROS_TYPE_MESSAGE,  // type
    0,  // upper bound of string
    NULL,  // members of sub message (initialized later)
    false,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs__msg__Zone, polygon),  // bytes offset in struct
    NULL,  // default value
    NULL,  // size() function pointer
    NULL,  // get_const(index) function pointer
    NULL,  // get(index) function pointer
    NULL,  // fetch(index, &value) function pointer
    NULL,  // assign(index, value) function pointer
    NULL  // resize(index) function pointer
  },
  {
    "neighbors",  // name
    rosidl_typesupport_introspection_c__ROS_TYPE_STRING,  // type
    0,  // upper bound of string
    NULL,  // members of sub message
    true,  // is array
    0,  // array size
    false,  // is upper bound
    offsetof(bird_deterrent_vineyard_msgs__msg__Zone, neighbors),  // bytes offset in struct
    NULL,  // default value
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__size_function__Zone__neighbors,  // size() function pointer
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_const_function__Zone__neighbors,  // get_const(index) function pointer
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__get_function__Zone__neighbors,  // get(index) function pointer
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__fetch_function__Zone__neighbors,  // fetch(index, &value) function pointer
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__assign_function__Zone__neighbors,  // assign(index, value) function pointer
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__resize_function__Zone__neighbors  // resize(index) function pointer
  }
};

static const rosidl_typesupport_introspection_c__MessageMembers bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_members = {
  "bird_deterrent_vineyard_msgs__msg",  // message namespace
  "Zone",  // message name
  3,  // number of fields
  sizeof(bird_deterrent_vineyard_msgs__msg__Zone),
  bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_member_array,  // message members
  bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_init_function,  // function to initialize message memory (memory has to be allocated)
  bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_fini_function  // function to terminate message instance (will not free memory)
};

// this is not const since it must be initialized on first access
// since C does not allow non-integral compile-time constants
static rosidl_message_type_support_t bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_type_support_handle = {
  0,
  &bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_members,
  get_message_typesupport_handle_function,
};

ROSIDL_TYPESUPPORT_INTROSPECTION_C_EXPORT_bird_deterrent_vineyard_msgs
const rosidl_message_type_support_t *
ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_introspection_c, bird_deterrent_vineyard_msgs, msg, Zone)() {
  bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_member_array[1].members_ =
    ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(rosidl_typesupport_introspection_c, bird_deterrent_vineyard_msgs, msg, Polygon2D)();
  if (!bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_type_support_handle.typesupport_identifier) {
    bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_type_support_handle.typesupport_identifier =
      rosidl_typesupport_introspection_c__identifier;
  }
  return &bird_deterrent_vineyard_msgs__msg__Zone__rosidl_typesupport_introspection_c__Zone_message_type_support_handle;
}
#ifdef __cplusplus
}
#endif
