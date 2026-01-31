// generated from rosidl_generator_c/resource/idl__functions.c.em
// with input from bird_deterrent_vineyard_msgs:msg/RobotPose.idl
// generated code does not contain a copyright notice
#include "bird_deterrent_vineyard_msgs/msg/detail/robot_pose__functions.h"

#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "rcutils/allocator.h"


// Include directives for member types
// Member `robot_id`
#include "rosidl_runtime_c/string_functions.h"

bool
bird_deterrent_vineyard_msgs__msg__RobotPose__init(bird_deterrent_vineyard_msgs__msg__RobotPose * msg)
{
  if (!msg) {
    return false;
  }
  // t
  // robot_id
  if (!rosidl_runtime_c__String__init(&msg->robot_id)) {
    bird_deterrent_vineyard_msgs__msg__RobotPose__fini(msg);
    return false;
  }
  // x
  // y
  return true;
}

void
bird_deterrent_vineyard_msgs__msg__RobotPose__fini(bird_deterrent_vineyard_msgs__msg__RobotPose * msg)
{
  if (!msg) {
    return;
  }
  // t
  // robot_id
  rosidl_runtime_c__String__fini(&msg->robot_id);
  // x
  // y
}

bool
bird_deterrent_vineyard_msgs__msg__RobotPose__are_equal(const bird_deterrent_vineyard_msgs__msg__RobotPose * lhs, const bird_deterrent_vineyard_msgs__msg__RobotPose * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  // t
  if (lhs->t != rhs->t) {
    return false;
  }
  // robot_id
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->robot_id), &(rhs->robot_id)))
  {
    return false;
  }
  // x
  if (lhs->x != rhs->x) {
    return false;
  }
  // y
  if (lhs->y != rhs->y) {
    return false;
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__RobotPose__copy(
  const bird_deterrent_vineyard_msgs__msg__RobotPose * input,
  bird_deterrent_vineyard_msgs__msg__RobotPose * output)
{
  if (!input || !output) {
    return false;
  }
  // t
  output->t = input->t;
  // robot_id
  if (!rosidl_runtime_c__String__copy(
      &(input->robot_id), &(output->robot_id)))
  {
    return false;
  }
  // x
  output->x = input->x;
  // y
  output->y = input->y;
  return true;
}

bird_deterrent_vineyard_msgs__msg__RobotPose *
bird_deterrent_vineyard_msgs__msg__RobotPose__create()
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__RobotPose * msg = (bird_deterrent_vineyard_msgs__msg__RobotPose *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__RobotPose), allocator.state);
  if (!msg) {
    return NULL;
  }
  memset(msg, 0, sizeof(bird_deterrent_vineyard_msgs__msg__RobotPose));
  bool success = bird_deterrent_vineyard_msgs__msg__RobotPose__init(msg);
  if (!success) {
    allocator.deallocate(msg, allocator.state);
    return NULL;
  }
  return msg;
}

void
bird_deterrent_vineyard_msgs__msg__RobotPose__destroy(bird_deterrent_vineyard_msgs__msg__RobotPose * msg)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (msg) {
    bird_deterrent_vineyard_msgs__msg__RobotPose__fini(msg);
  }
  allocator.deallocate(msg, allocator.state);
}


bool
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__init(bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * array, size_t size)
{
  if (!array) {
    return false;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__RobotPose * data = NULL;

  if (size) {
    data = (bird_deterrent_vineyard_msgs__msg__RobotPose *)allocator.zero_allocate(size, sizeof(bird_deterrent_vineyard_msgs__msg__RobotPose), allocator.state);
    if (!data) {
      return false;
    }
    // initialize all array elements
    size_t i;
    for (i = 0; i < size; ++i) {
      bool success = bird_deterrent_vineyard_msgs__msg__RobotPose__init(&data[i]);
      if (!success) {
        break;
      }
    }
    if (i < size) {
      // if initialization failed finalize the already initialized array elements
      for (; i > 0; --i) {
        bird_deterrent_vineyard_msgs__msg__RobotPose__fini(&data[i - 1]);
      }
      allocator.deallocate(data, allocator.state);
      return false;
    }
  }
  array->data = data;
  array->size = size;
  array->capacity = size;
  return true;
}

void
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__fini(bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * array)
{
  if (!array) {
    return;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();

  if (array->data) {
    // ensure that data and capacity values are consistent
    assert(array->capacity > 0);
    // finalize all array elements
    for (size_t i = 0; i < array->capacity; ++i) {
      bird_deterrent_vineyard_msgs__msg__RobotPose__fini(&array->data[i]);
    }
    allocator.deallocate(array->data, allocator.state);
    array->data = NULL;
    array->size = 0;
    array->capacity = 0;
  } else {
    // ensure that data, size, and capacity values are consistent
    assert(0 == array->size);
    assert(0 == array->capacity);
  }
}

bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence *
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__create(size_t size)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * array = (bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence), allocator.state);
  if (!array) {
    return NULL;
  }
  bool success = bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__init(array, size);
  if (!success) {
    allocator.deallocate(array, allocator.state);
    return NULL;
  }
  return array;
}

void
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__destroy(bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * array)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (array) {
    bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__fini(array);
  }
  allocator.deallocate(array, allocator.state);
}

bool
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__are_equal(const bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * lhs, const bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  if (lhs->size != rhs->size) {
    return false;
  }
  for (size_t i = 0; i < lhs->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__RobotPose__are_equal(&(lhs->data[i]), &(rhs->data[i]))) {
      return false;
    }
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence__copy(
  const bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * input,
  bird_deterrent_vineyard_msgs__msg__RobotPose__Sequence * output)
{
  if (!input || !output) {
    return false;
  }
  if (output->capacity < input->size) {
    const size_t allocation_size =
      input->size * sizeof(bird_deterrent_vineyard_msgs__msg__RobotPose);
    rcutils_allocator_t allocator = rcutils_get_default_allocator();
    bird_deterrent_vineyard_msgs__msg__RobotPose * data =
      (bird_deterrent_vineyard_msgs__msg__RobotPose *)allocator.reallocate(
      output->data, allocation_size, allocator.state);
    if (!data) {
      return false;
    }
    // If reallocation succeeded, memory may or may not have been moved
    // to fulfill the allocation request, invalidating output->data.
    output->data = data;
    for (size_t i = output->capacity; i < input->size; ++i) {
      if (!bird_deterrent_vineyard_msgs__msg__RobotPose__init(&output->data[i])) {
        // If initialization of any new item fails, roll back
        // all previously initialized items. Existing items
        // in output are to be left unmodified.
        for (; i-- > output->capacity; ) {
          bird_deterrent_vineyard_msgs__msg__RobotPose__fini(&output->data[i]);
        }
        return false;
      }
    }
    output->capacity = input->size;
  }
  output->size = input->size;
  for (size_t i = 0; i < input->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__RobotPose__copy(
        &(input->data[i]), &(output->data[i])))
    {
      return false;
    }
  }
  return true;
}
