// generated from rosidl_generator_c/resource/idl__functions.c.em
// with input from bird_deterrent_vineyard_msgs:msg/TaskStatus.idl
// generated code does not contain a copyright notice
#include "bird_deterrent_vineyard_msgs/msg/detail/task_status__functions.h"

#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "rcutils/allocator.h"


// Include directives for member types
// Member `event`
// Member `robot_id`
// Member `task_id`
// Member `type`
// Member `role`
// Member `extra`
#include "rosidl_runtime_c/string_functions.h"

bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__init(bird_deterrent_vineyard_msgs__msg__TaskStatus * msg)
{
  if (!msg) {
    return false;
  }
  // t
  // event
  if (!rosidl_runtime_c__String__init(&msg->event)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  // robot_id
  if (!rosidl_runtime_c__String__init(&msg->robot_id)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  // task_id
  if (!rosidl_runtime_c__String__init(&msg->task_id)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__init(&msg->type)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  // x
  // y
  // role
  if (!rosidl_runtime_c__String__init(&msg->role)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  // extra
  if (!rosidl_runtime_c__String__init(&msg->extra)) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
    return false;
  }
  return true;
}

void
bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(bird_deterrent_vineyard_msgs__msg__TaskStatus * msg)
{
  if (!msg) {
    return;
  }
  // t
  // event
  rosidl_runtime_c__String__fini(&msg->event);
  // robot_id
  rosidl_runtime_c__String__fini(&msg->robot_id);
  // task_id
  rosidl_runtime_c__String__fini(&msg->task_id);
  // type
  rosidl_runtime_c__String__fini(&msg->type);
  // x
  // y
  // role
  rosidl_runtime_c__String__fini(&msg->role);
  // extra
  rosidl_runtime_c__String__fini(&msg->extra);
}

bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__are_equal(const bird_deterrent_vineyard_msgs__msg__TaskStatus * lhs, const bird_deterrent_vineyard_msgs__msg__TaskStatus * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  // t
  if (lhs->t != rhs->t) {
    return false;
  }
  // event
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->event), &(rhs->event)))
  {
    return false;
  }
  // robot_id
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->robot_id), &(rhs->robot_id)))
  {
    return false;
  }
  // task_id
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->task_id), &(rhs->task_id)))
  {
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->type), &(rhs->type)))
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
  // role
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->role), &(rhs->role)))
  {
    return false;
  }
  // extra
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->extra), &(rhs->extra)))
  {
    return false;
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__copy(
  const bird_deterrent_vineyard_msgs__msg__TaskStatus * input,
  bird_deterrent_vineyard_msgs__msg__TaskStatus * output)
{
  if (!input || !output) {
    return false;
  }
  // t
  output->t = input->t;
  // event
  if (!rosidl_runtime_c__String__copy(
      &(input->event), &(output->event)))
  {
    return false;
  }
  // robot_id
  if (!rosidl_runtime_c__String__copy(
      &(input->robot_id), &(output->robot_id)))
  {
    return false;
  }
  // task_id
  if (!rosidl_runtime_c__String__copy(
      &(input->task_id), &(output->task_id)))
  {
    return false;
  }
  // type
  if (!rosidl_runtime_c__String__copy(
      &(input->type), &(output->type)))
  {
    return false;
  }
  // x
  output->x = input->x;
  // y
  output->y = input->y;
  // role
  if (!rosidl_runtime_c__String__copy(
      &(input->role), &(output->role)))
  {
    return false;
  }
  // extra
  if (!rosidl_runtime_c__String__copy(
      &(input->extra), &(output->extra)))
  {
    return false;
  }
  return true;
}

bird_deterrent_vineyard_msgs__msg__TaskStatus *
bird_deterrent_vineyard_msgs__msg__TaskStatus__create()
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__TaskStatus * msg = (bird_deterrent_vineyard_msgs__msg__TaskStatus *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__TaskStatus), allocator.state);
  if (!msg) {
    return NULL;
  }
  memset(msg, 0, sizeof(bird_deterrent_vineyard_msgs__msg__TaskStatus));
  bool success = bird_deterrent_vineyard_msgs__msg__TaskStatus__init(msg);
  if (!success) {
    allocator.deallocate(msg, allocator.state);
    return NULL;
  }
  return msg;
}

void
bird_deterrent_vineyard_msgs__msg__TaskStatus__destroy(bird_deterrent_vineyard_msgs__msg__TaskStatus * msg)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (msg) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(msg);
  }
  allocator.deallocate(msg, allocator.state);
}


bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__init(bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * array, size_t size)
{
  if (!array) {
    return false;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__TaskStatus * data = NULL;

  if (size) {
    data = (bird_deterrent_vineyard_msgs__msg__TaskStatus *)allocator.zero_allocate(size, sizeof(bird_deterrent_vineyard_msgs__msg__TaskStatus), allocator.state);
    if (!data) {
      return false;
    }
    // initialize all array elements
    size_t i;
    for (i = 0; i < size; ++i) {
      bool success = bird_deterrent_vineyard_msgs__msg__TaskStatus__init(&data[i]);
      if (!success) {
        break;
      }
    }
    if (i < size) {
      // if initialization failed finalize the already initialized array elements
      for (; i > 0; --i) {
        bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(&data[i - 1]);
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
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__fini(bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * array)
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
      bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(&array->data[i]);
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

bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence *
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__create(size_t size)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * array = (bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence *)allocator.allocate(sizeof(bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence), allocator.state);
  if (!array) {
    return NULL;
  }
  bool success = bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__init(array, size);
  if (!success) {
    allocator.deallocate(array, allocator.state);
    return NULL;
  }
  return array;
}

void
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__destroy(bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * array)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (array) {
    bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__fini(array);
  }
  allocator.deallocate(array, allocator.state);
}

bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__are_equal(const bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * lhs, const bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  if (lhs->size != rhs->size) {
    return false;
  }
  for (size_t i = 0; i < lhs->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__TaskStatus__are_equal(&(lhs->data[i]), &(rhs->data[i]))) {
      return false;
    }
  }
  return true;
}

bool
bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence__copy(
  const bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * input,
  bird_deterrent_vineyard_msgs__msg__TaskStatus__Sequence * output)
{
  if (!input || !output) {
    return false;
  }
  if (output->capacity < input->size) {
    const size_t allocation_size =
      input->size * sizeof(bird_deterrent_vineyard_msgs__msg__TaskStatus);
    rcutils_allocator_t allocator = rcutils_get_default_allocator();
    bird_deterrent_vineyard_msgs__msg__TaskStatus * data =
      (bird_deterrent_vineyard_msgs__msg__TaskStatus *)allocator.reallocate(
      output->data, allocation_size, allocator.state);
    if (!data) {
      return false;
    }
    // If reallocation succeeded, memory may or may not have been moved
    // to fulfill the allocation request, invalidating output->data.
    output->data = data;
    for (size_t i = output->capacity; i < input->size; ++i) {
      if (!bird_deterrent_vineyard_msgs__msg__TaskStatus__init(&output->data[i])) {
        // If initialization of any new item fails, roll back
        // all previously initialized items. Existing items
        // in output are to be left unmodified.
        for (; i-- > output->capacity; ) {
          bird_deterrent_vineyard_msgs__msg__TaskStatus__fini(&output->data[i]);
        }
        return false;
      }
    }
    output->capacity = input->size;
  }
  output->size = input->size;
  for (size_t i = 0; i < input->size; ++i) {
    if (!bird_deterrent_vineyard_msgs__msg__TaskStatus__copy(
        &(input->data[i]), &(output->data[i])))
    {
      return false;
    }
  }
  return true;
}
